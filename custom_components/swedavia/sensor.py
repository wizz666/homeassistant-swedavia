"""Sensor platform for Swedavia integration."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import AIRPORTS, CONF_AIRPORTS, DOMAIN

_LOGGER = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helper functions – robust field extraction with multiple fallback names
# ---------------------------------------------------------------------------

def _try_get(obj, *keys, default=None):
    """Try multiple key names on a dict and return the first match."""
    if not isinstance(obj, dict):
        return default
    for k in keys:
        v = obj.get(k)
        if v is not None:
            return v
    return default


def _parse_dt(value) -> datetime | None:
    """Parse ISO 8601 datetime string to UTC-aware datetime."""
    if not value:
        return None
    try:
        s = str(value).strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            # No timezone info – assume UTC (we use the raw string for display)
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def _get_nested_utc(flight: dict, time_key: str) -> str | None:
    """Extract scheduledUtc from a nested time object and convert to local HH:MM.

    Swedavia API returns times as: {"departureTime": {"scheduledUtc": "2026-03-11T10:30:00Z"}}
    We convert UTC → local time (Europe/Stockholm, CET/CEST).
    """
    obj = flight.get(time_key)
    if not isinstance(obj, dict):
        return None
    utc_str = obj.get("scheduledUtc") or obj.get("estimatedUtc") or obj.get("actualUtc")
    if not utc_str:
        return None
    dt = _parse_dt(utc_str)
    if dt is None:
        return None
    # Convert UTC → Europe/Stockholm (CET=UTC+1, CEST=UTC+2)
    # Use a simple heuristic: last Sun Mar → last Sun Oct = CEST (UTC+2), else CET (UTC+1)
    import calendar as _cal
    m = dt.month
    if m > 3 and m < 10:
        offset_h = 2
    elif m == 3:
        # After last Sunday of March → CEST
        last_sun = max(
            [d for d in range(25, 32) if _cal.weekday(dt.year, 3, d) == 6 if d <= 31],
            default=31,
        )
        offset_h = 2 if dt.day > last_sun or (dt.day == last_sun and dt.hour >= 1) else 1
    elif m == 10:
        last_sun = max(
            [d for d in range(25, 32) if _cal.weekday(dt.year, 10, d) == 6 if d <= 31],
            default=31,
        )
        offset_h = 1 if dt.day > last_sun or (dt.day == last_sun and dt.hour >= 1) else 2
    else:
        offset_h = 1
    from datetime import timedelta
    local_dt = dt + timedelta(hours=offset_h)
    return local_dt.strftime("%H:%M")


def _get_nested_utc_dt(flight: dict, time_key: str) -> datetime | None:
    """Extract scheduledUtc from a nested time object as a UTC datetime."""
    obj = flight.get(time_key)
    if not isinstance(obj, dict):
        return None
    utc_str = obj.get("scheduledUtc") or obj.get("estimatedUtc") or obj.get("actualUtc")
    if not utc_str:
        return None
    return _parse_dt(utc_str)


def _flight_time_str(flight: dict, direction: str) -> str:
    """Extract scheduled time as 'HH:MM' string (local CET/CEST).

    Handles Swedavia API nested structure: departureTime.scheduledUtc / arrivalTime.scheduledUtc
    Falls back to legacy flat field names.
    """
    # Primary: Swedavia API nested structure (confirmed format)
    if direction == "departure":
        t = _get_nested_utc(flight, "departureTime")
        if t:
            return t
        fallback_keys = (
            "scheduledDepartureDateTime", "scheduledDepartureTime",
            "departureDateTime", "scheduledTime", "scheduled", "STD",
        )
    else:
        t = _get_nested_utc(flight, "arrivalTime")
        if t:
            return t
        fallback_keys = (
            "scheduledArrivalDateTime", "scheduledArrivalTime",
            "arrivalDateTime", "scheduledTime", "scheduled", "STA",
        )

    for k in fallback_keys:
        v = flight.get(k)
        if v and isinstance(v, str):
            if "T" in v:
                parts = v.split("T")
                if len(parts) > 1:
                    return parts[1][:5]
            if len(v) >= 5 and v[2:3] == ":":
                return v[:5]
        elif v is not None:
            s = str(v)
            if "T" in s:
                return s.split("T")[1][:5]
    return "?"


def _flight_sched_time(flight: dict, direction: str) -> datetime | None:
    """Extract scheduled time as UTC datetime object (for sorting/filtering)."""
    # Primary: Swedavia API nested structure
    if direction == "departure":
        dt = _get_nested_utc_dt(flight, "departureTime")
        if dt:
            return dt
        fallback_keys = (
            "scheduledDepartureDateTime", "scheduledDepartureTime",
            "departureDateTime", "scheduledTime", "scheduled", "STD",
        )
    else:
        dt = _get_nested_utc_dt(flight, "arrivalTime")
        if dt:
            return dt
        fallback_keys = (
            "scheduledArrivalDateTime", "scheduledArrivalTime",
            "arrivalDateTime", "scheduledTime", "scheduled", "STA",
        )

    for k in fallback_keys:
        v = flight.get(k)
        if v:
            parsed = _parse_dt(v)
            if parsed:
                return parsed
    return None


def _flight_id(flight: dict) -> str:
    return _try_get(flight, "flightId", "flightNumber", "flight", "iata", "FlightId", default="???")


def _flight_destination_iata(flight: dict) -> str:
    # Primary: Swedavia API nested flightLegIdentifier
    leg = flight.get("flightLegIdentifier")
    if isinstance(leg, dict):
        v = leg.get("arrivalAirportIata")
        if v:
            return v
    return _try_get(
        flight,
        "arrivalAirportIATA", "destinationIATA", "destination",
        "arrivalIATA", "ArrIATA", "toIATA",
        default="?",
    )


def _flight_origin_iata(flight: dict) -> str:
    # Primary: Swedavia API nested flightLegIdentifier
    leg = flight.get("flightLegIdentifier")
    if isinstance(leg, dict):
        v = leg.get("departureAirportIata")
        if v:
            return v
    return _try_get(
        flight,
        "departureAirportIATA", "originIATA", "origin",
        "depIATA", "DepIATA", "fromIATA",
        default="?",
    )


def _flight_destination_name(flight: dict) -> str:
    return _try_get(
        flight,
        "arrivalAirportSwedish", "arrivalAirportEnglish",
        "destinationName", "arrivalCity", "toCity",
        default="",
    )


def _flight_origin_name(flight: dict) -> str:
    return _try_get(
        flight,
        "departureAirportSwedish", "departureAirportEnglish",
        "originName", "departureCity", "fromCity",
        default="",
    )


def _flight_status(flight: dict) -> str:
    # Primary: Swedavia API nested locationAndStatus
    loc = flight.get("locationAndStatus")
    if isinstance(loc, dict):
        v = loc.get("flightLegStatusEnglish") or loc.get("flightLegStatus") or ""
        if v:
            return v
    return _try_get(
        flight,
        "flightLegStatus", "status", "flightStatus", "Status",
        default="",
    ) or ""


def _flight_airline(flight: dict) -> str:
    # Primary: Swedavia API nested airlineOperator
    op = flight.get("airlineOperator")
    if isinstance(op, dict):
        v = op.get("iata") or op.get("name", "")
        if v:
            return v
    return _try_get(flight, "airlineIATA", "airline", "Airline", default="")


def _normalize_status(status: str) -> tuple[str, str]:
    """Return (display_text, icon_emoji) for a raw flight status string.

    Handles both Swedavia API English values (e.g. 'On Time', 'Deleted')
    and legacy short codes (e.g. 'ONT', 'DEL').
    """
    if not status:
        return ("", "❔")
    s = status.upper().replace("_", " ").replace("-", " ")
    # Swedavia-specific codes (short codes + full English)
    if s in ("ONT", "ON TIME") or "ON TIME" in s:
        return ("I TID", "✅")
    if s in ("DEL", "DELETED", "CANCELLED", "CANCEL", "INSTA") or any(
        k in s for k in ("CANCEL", "INSTÄLL", "DELETED", "REMOVE")
    ):
        return ("INSTÄLLT", "🚫")
    if s in ("DEP", "DEPARTED") or any(k in s for k in ("DEPARTED", "AVGÅTT", "LEFT GATE")):
        return ("AVGÅTT", "🛫")
    if s in ("ARR", "ARRIVED", "LANDED") or any(k in s for k in ("LANDED", "ANKOMMIT", "ARRIVED")):
        return ("ANKOMMIT", "🛬")
    if s in ("BOA", "BOARDING") or "BOARDING" in s or "OMBORDSTIGNING" in s:
        return ("BOARDING", "🚪")
    if s in ("DLY", "DELAYED") or any(k in s for k in ("DELAY", "FÖRSEN", "LATE")):
        return ("FÖRSENAT", "⚠️")
    if "GATE CLOSE" in s or "LAST CALL" in s or "SISTA" in s:
        return ("SISTA CALL", "🔔")
    if any(k in s for k in ("IN AIR", "IN FLIGHT", "AIRBORNE", "FLYING")):
        return ("I LUFTEN", "✈️")
    if any(k in s for k in ("EXPECTED", "ESTIMATED", "BERÄKNAD")):
        return ("BERÄKNAD", "🕐")
    if "SCHEDULE" in s:
        return ("PLANERAD", "📅")
    # Return raw status (truncated) if not recognised
    return (status[:14], "❔")


def _get_next_flight(flights: list, direction: str) -> dict | None:
    """Return the next upcoming flight (up to 30 min in the past)."""
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(minutes=30)
    upcoming: list[tuple[datetime, dict]] = []

    for f in flights:
        if not isinstance(f, dict):
            continue
        dt = _flight_sched_time(f, direction)
        if dt is not None and dt >= cutoff:
            upcoming.append((dt, f))

    upcoming.sort(key=lambda x: x[0])
    return upcoming[0][1] if upcoming else None


def _build_flight_entry(flight: dict, direction: str) -> dict | None:
    """Build a standardized dict for use in upcoming_flights attribute."""
    time_str = _flight_time_str(flight, direction)
    sched_dt = _flight_sched_time(flight, direction)

    status_raw = _flight_status(flight)
    status_text, status_icon = _normalize_status(status_raw)

    entry: dict = {
        "flight_id": _flight_id(flight),
        "airline": _flight_airline(flight),
        "scheduled": time_str,
        "status": status_text,
        "status_icon": status_icon,
        # Private sort key (UTC ISO string)
        "_sort": sched_dt.isoformat() if sched_dt else time_str,
    }

    # Estimated time (raw string, same TZ treatment as scheduled)
    if direction == "departure":
        for k in ("estimatedDepartureDateTime", "estimatedTime", "ETD"):
            v = flight.get(k)
            if v and isinstance(v, str) and "T" in v:
                entry["estimated"] = v.split("T")[1][:5]
                break
    else:
        for k in ("estimatedArrivalDateTime", "estimatedTime", "ETA"):
            v = flight.get(k)
            if v and isinstance(v, str) and "T" in v:
                entry["estimated"] = v.split("T")[1][:5]
                break

    loc = flight.get("locationAndStatus", {})
    if not isinstance(loc, dict):
        loc = {}

    if direction == "departure":
        entry["destination"] = _flight_destination_iata(flight)
        entry["destination_name"] = _flight_destination_name(flight)
        entry["gate"] = (
            _try_get(loc, "gate", "gateCode", "Gate")
            or _try_get(flight, "gate", "gateCode")
        )
        entry["terminal"] = _try_get(loc, "terminal", "terminalCode") or _try_get(flight, "terminal")
    else:
        entry["origin"] = _flight_origin_iata(flight)
        entry["origin_name"] = _flight_origin_name(flight)
        entry["belt"] = (
            _try_get(loc, "belt", "baggageBelt", "bagageBelt")
            or _try_get(flight, "belt", "baggage_belt")
        )
        entry["terminal"] = _try_get(loc, "terminal") or _try_get(flight, "terminal")

    return entry


def _checkpoint_wait(cp: dict) -> int | None:
    # Swedavia API: currentProjectedWaitTime
    for k in ("currentProjectedWaitTime", "waitTimeMinutes", "waitTime", "wait_time", "WaitTime", "minutes", "time"):
        v = cp.get(k)
        if v is not None:
            try:
                return int(v)
            except (TypeError, ValueError):
                pass
    return None


def _checkpoint_name(cp: dict) -> str:
    # Swedavia API: queueName
    return _try_get(cp, "queueName", "checkpointName", "name", "Name", "checkpoint", default="Unknown")


def _checkpoint_open(cp: dict):
    # Swedavia API: no direct open/closed field; derive from overflow
    overflow = cp.get("overflow")
    if overflow is not None:
        return not overflow  # not overflowing = open
    return _try_get(cp, "isOpen", "open", "Open", "active", default=None)


# ---------------------------------------------------------------------------
# Platform setup
# ---------------------------------------------------------------------------

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Swedavia sensors from config entry."""
    store = hass.data[DOMAIN][entry.entry_id]
    flight_coord = store["flight_coord"]
    queue_coord = store["queue_coord"]
    airports: list[str] = entry.options.get(CONF_AIRPORTS, entry.data[CONF_AIRPORTS])

    entities: list[SensorEntity] = []
    for airport in airports:
        airport_name = AIRPORTS.get(airport, airport)
        dev = DeviceInfo(
            identifiers={(DOMAIN, airport)},
            name=f"Swedavia {airport_name}",
            manufacturer="Swedavia",
            model=f"{airport} – {airport_name}",
            configuration_url="https://apideveloper.swedavia.se/",
        )
        entities.append(SvedaviaNextFlightSensor(flight_coord, airport, "departure", dev))
        entities.append(SvedaviaNextFlightSensor(flight_coord, airport, "arrival", dev))
        entities.append(SvedaviaFlightCountSensor(flight_coord, airport, "departures", dev))
        entities.append(SvedaviaFlightCountSensor(flight_coord, airport, "arrivals", dev))
        entities.append(SvedaviaWaitTimeSensor(queue_coord, airport, dev))

    async_add_entities(entities)


# ---------------------------------------------------------------------------
# Base entity
# ---------------------------------------------------------------------------

class SvedaviaEntity(CoordinatorEntity, SensorEntity):
    """Base class for Swedavia sensors."""

    def __init__(self, coordinator, airport: str, device_info: DeviceInfo) -> None:
        super().__init__(coordinator)
        self._airport = airport
        self._attr_device_info = device_info

    @property
    def available(self) -> bool:
        if not self.coordinator.last_update_success:
            return False
        d = self.coordinator.data
        return bool(d and self._airport in d)


# ---------------------------------------------------------------------------
# Next flight sensor (shows just the immediate next flight)
# ---------------------------------------------------------------------------

class SvedaviaNextFlightSensor(SvedaviaEntity):
    """Shows the next upcoming departure or arrival."""

    def __init__(self, coordinator, airport: str, direction: str, device_info: DeviceInfo) -> None:
        super().__init__(coordinator, airport, device_info)
        self._direction = direction

        if direction == "departure":
            self._attr_name = f"Swedavia {airport} Next Departure"
            self._attr_unique_id = f"swedavia_{airport}_next_departure"
            self._attr_icon = "mdi:airplane-takeoff"
        else:
            self._attr_name = f"Swedavia {airport} Next Arrival"
            self._attr_unique_id = f"swedavia_{airport}_next_arrival"
            self._attr_icon = "mdi:airplane-landing"

    def _flights(self) -> list:
        d = self.coordinator.data or {}
        key = "departures" if self._direction == "departure" else "arrivals"
        return (d.get(self._airport) or {}).get(key, [])

    @property
    def native_value(self) -> str | None:
        flight = _get_next_flight(self._flights(), self._direction)
        if not flight:
            return "Inga"

        fid = _flight_id(flight)
        time_str = _flight_time_str(flight, self._direction)

        if self._direction == "departure":
            dest = _flight_destination_iata(flight)
            return f"{fid} → {dest} {time_str}"
        else:
            orig = _flight_origin_iata(flight)
            return f"{fid} ← {orig} {time_str}"

    @property
    def extra_state_attributes(self) -> dict:
        flights = self._flights()
        flight = _get_next_flight(flights, self._direction)
        attrs: dict = {"total_flights_today": len(flights)}

        if not flight:
            return attrs

        loc = flight.get("locationAndStatus", {}) if isinstance(flight.get("locationAndStatus"), dict) else {}
        status_text, status_icon = _normalize_status(_flight_status(flight))

        attrs.update(
            {
                "flight_id": _flight_id(flight),
                "airline": _flight_airline(flight),
                "scheduled_time": _flight_time_str(flight, self._direction),
                "status": status_text,
                "status_icon": status_icon,
                "terminal": _try_get(loc, "terminal", "terminalCode") or _try_get(flight, "terminal"),
            }
        )

        if self._direction == "departure":
            attrs["destination_iata"] = _flight_destination_iata(flight)
            attrs["destination_name"] = _flight_destination_name(flight)
            attrs["gate"] = (
                _try_get(loc, "gate", "gateCode", "Gate")
                or _try_get(flight, "gate", "gateCode")
            )
        else:
            attrs["origin_iata"] = _flight_origin_iata(flight)
            attrs["origin_name"] = _flight_origin_name(flight)
            attrs["belt"] = (
                _try_get(loc, "belt", "baggageBelt", "bagageBelt")
                or _try_get(flight, "belt", "baggage_belt")
            )

        return attrs


# ---------------------------------------------------------------------------
# Flight count sensor (with full upcoming_flights list as attribute)
# ---------------------------------------------------------------------------

class SvedaviaFlightCountSensor(SvedaviaEntity):
    """Total departures/arrivals today, plus a full upcoming flight list."""

    def __init__(self, coordinator, airport: str, flight_type: str, device_info: DeviceInfo) -> None:
        super().__init__(coordinator, airport, device_info)
        self._flight_type = flight_type

        if flight_type == "departures":
            self._attr_name = f"Swedavia {airport} Departures Today"
            self._attr_unique_id = f"swedavia_{airport}_departures_today"
            self._attr_icon = "mdi:airplane-takeoff"
        else:
            self._attr_name = f"Swedavia {airport} Arrivals Today"
            self._attr_unique_id = f"swedavia_{airport}_arrivals_today"
            self._attr_icon = "mdi:airplane-landing"

        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_native_unit_of_measurement = "flights"

    def _flights(self) -> list:
        d = self.coordinator.data or {}
        return (d.get(self._airport) or {}).get(self._flight_type, [])

    @property
    def native_value(self) -> int:
        return len(self._flights())

    @property
    def extra_state_attributes(self) -> dict:
        flights = self._flights()
        direction = "departure" if self._flight_type == "departures" else "arrival"

        statuses: dict[str, int] = {}
        upcoming: list[dict] = []

        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(minutes=30)

        for f in flights:
            if not isinstance(f, dict):
                continue

            # Status breakdown (all flights)
            s = _flight_status(f) or "UNKNOWN"
            statuses[s] = statuses.get(s, 0) + 1

            # Build entry for upcoming list
            entry = _build_flight_entry(f, direction)
            if entry is None:
                continue

            # Include if future or recent (within 30 min)
            sched_dt = _flight_sched_time(f, direction)
            if sched_dt is None or sched_dt >= cutoff:
                upcoming.append(entry)

        # Sort by scheduled time and keep max 20
        upcoming.sort(key=lambda x: x.get("_sort", ""))
        for e in upcoming:
            e.pop("_sort", None)

        return {
            "status_breakdown": statuses,
            "upcoming_flights": upcoming[:20],
        }


# ---------------------------------------------------------------------------
# Security wait time sensor
# ---------------------------------------------------------------------------

class SvedaviaWaitTimeSensor(SvedaviaEntity):
    """Security wait time (max across all checkpoints)."""

    def __init__(self, coordinator, airport: str, device_info: DeviceInfo) -> None:
        super().__init__(coordinator, airport, device_info)
        self._attr_name = f"Swedavia {airport} Security Wait"
        self._attr_unique_id = f"swedavia_{airport}_security_wait"
        self._attr_icon = "mdi:clock-fast"
        self._attr_native_unit_of_measurement = UnitOfTime.MINUTES
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_device_class = SensorDeviceClass.DURATION

    def _checkpoints(self) -> list:
        d = self.coordinator.data or {}
        return (d.get(self._airport) or {}).get("checkpoints", [])

    @property
    def native_value(self) -> int | None:
        checkpoints = self._checkpoints()
        if not checkpoints:
            return None

        max_wait: int | None = None
        for cp in checkpoints:
            if isinstance(cp, dict):
                w = _checkpoint_wait(cp)
                if w is not None and (max_wait is None or w > max_wait):
                    max_wait = w
        return max_wait

    @property
    def extra_state_attributes(self) -> dict:
        checkpoints = self._checkpoints()
        parsed = [
            {
                "name": _checkpoint_name(cp),
                "wait_minutes": _checkpoint_wait(cp),
                "open": _checkpoint_open(cp),
            }
            for cp in checkpoints
            if isinstance(cp, dict)
        ]
        return {"checkpoints": parsed}
