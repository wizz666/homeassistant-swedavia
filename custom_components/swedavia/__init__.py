"""Swedavia integration – flight information and security queue times."""

from __future__ import annotations

import logging
from datetime import date

import aiohttp
import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    API_ACCEPT_HEADER,
    API_KEY_HEADER,
    CONF_AIRPORTS,
    CONF_FLIGHTINFO_INTERVAL,
    CONF_FLIGHTINFO_KEY,
    CONF_WAITTIME_INTERVAL,
    CONF_WAITTIME_KEY,
    DEFAULT_FLIGHTINFO_INTERVAL,
    DEFAULT_WAITTIME_INTERVAL,
    DOMAIN,
    FLIGHTINFO_BASE,
    REQUEST_TIMEOUT,
    WAITTIME_BASE,
)
from .coordinator import SvedaviaFlightCoordinator, SvedaviaQueueCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["sensor"]

SERVICE_SEARCH_FLIGHT = "search_flight"
SERVICE_SCHEMA = vol.Schema(
    {
        vol.Required("flight_id"): str,
        vol.Optional("airport"): str,
    }
)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Swedavia from a config entry."""
    airports: list[str] = entry.options.get(CONF_AIRPORTS, entry.data[CONF_AIRPORTS])
    fi_key: str = entry.data[CONF_FLIGHTINFO_KEY]
    wt_key: str = entry.data[CONF_WAITTIME_KEY]

    fi_interval = int(
        entry.options.get(
            CONF_FLIGHTINFO_INTERVAL,
            entry.data.get(CONF_FLIGHTINFO_INTERVAL, DEFAULT_FLIGHTINFO_INTERVAL),
        )
    )
    wt_interval = int(
        entry.options.get(
            CONF_WAITTIME_INTERVAL,
            entry.data.get(CONF_WAITTIME_INTERVAL, DEFAULT_WAITTIME_INTERVAL),
        )
    )

    flight_coord = SvedaviaFlightCoordinator(hass, airports, fi_key, fi_interval)
    queue_coord = SvedaviaQueueCoordinator(hass, airports, wt_key, wt_interval)

    try:
        await flight_coord.async_config_entry_first_refresh()
    except Exception as err:
        raise ConfigEntryNotReady(f"FlightInfo API unreachable: {err}") from err

    try:
        await queue_coord.async_config_entry_first_refresh()
    except Exception as err:
        raise ConfigEntryNotReady(f"WaitTime API unreachable: {err}") from err

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "flight_coord": flight_coord,
        "queue_coord": queue_coord,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))

    # Register search service (only once, even if multiple config entries exist)
    if not hass.services.has_service(DOMAIN, SERVICE_SEARCH_FLIGHT):
        hass.services.async_register(
            DOMAIN,
            SERVICE_SEARCH_FLIGHT,
            _make_search_service(hass),
            schema=SERVICE_SCHEMA,
        )

    _LOGGER.info(
        "Swedavia loaded – airports: %s, flight interval: %d min, wait interval: %d min",
        airports,
        fi_interval,
        wt_interval,
    )
    return True


def _make_search_service(hass: HomeAssistant):
    """Return a service handler that searches for a specific flight.

    Strategy:
    1. Search all coordinator caches (covers upcoming flights without API cost).
    2. If not found, make a live FlightInfo call to find it.
    The result is fired as a Swedavia event and logged for dashboard templates.
    """

    async def handle(call: ServiceCall) -> None:
        flight_id = call.data["flight_id"].strip().upper()
        requested_airport = call.data.get("airport", "").strip().upper() or None
        today = date.today().strftime("%Y-%m-%d")

        # ── Step 1: Search coordinator caches ──────────────────────────────
        found: dict | None = None
        found_airport: str = ""
        found_direction: str = ""

        for _entry_id, store in hass.data.get(DOMAIN, {}).items():
            coord = store.get("flight_coord")
            if not coord or not coord.data:
                continue
            for airport, airport_data in coord.data.items():
                if requested_airport and airport != requested_airport:
                    continue
                for direction in ("departures", "arrivals"):
                    for f in airport_data.get(direction, []):
                        fid = (
                            f.get("flightId") or f.get("flightNumber") or
                            f.get("flight") or f.get("iata") or ""
                        )
                        if fid.upper() == flight_id:
                            found = f
                            found_airport = airport
                            found_direction = direction
                            break
                    if found:
                        break
                if found:
                    break
            if found:
                break

        # ── Step 2: Live API call if not cached ─────────────────────────────
        if not found:
            airports_to_try = (
                [requested_airport]
                if requested_airport
                else list({
                    ap
                    for store in hass.data.get(DOMAIN, {}).values()
                    for ap in (store.get("flight_coord") and store["flight_coord"].data or {})
                })
            )
            # Try to find the API key from the first loaded entry
            fi_key: str = ""
            for e in hass.config_entries.async_entries(DOMAIN):
                fi_key = e.data.get(CONF_FLIGHTINFO_KEY, "")
                if fi_key:
                    break

            if fi_key:
                session = async_get_clientsession(hass)
                headers = {API_KEY_HEADER: fi_key, "Accept": API_ACCEPT_HEADER}
                timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)

                for airport in airports_to_try:
                    for direction in ("arrivals", "departures"):
                        url = f"{FLIGHTINFO_BASE}/{airport}/{direction}/{today}"
                        try:
                            async with session.get(url, headers=headers, timeout=timeout) as resp:
                                if resp.status == 200:
                                    raw = await resp.json(content_type=None)
                                    flights = raw if isinstance(raw, list) else raw.get("flights", [])
                                    for f in flights:
                                        fid = (
                                            f.get("flightId") or f.get("flightNumber") or
                                            f.get("flight") or f.get("iata") or ""
                                        )
                                        if fid.upper() == flight_id:
                                            found = f
                                            found_airport = airport
                                            found_direction = direction
                                            break
                        except Exception as err:
                            _LOGGER.debug("Live search error %s %s: %s", airport, direction, err)
                        if found:
                            break
                    if found:
                        break

        # ── Step 3: Fire event with result ──────────────────────────────────
        if found:
            _LOGGER.info(
                "Swedavia search: found %s at %s (%s)",
                flight_id, found_airport, found_direction,
            )
            hass.bus.async_fire(
                "swedavia_flight_found",
                {
                    "flight_id": flight_id,
                    "airport": found_airport,
                    "direction": found_direction,
                    "data": found,
                },
            )
            # Update search text helper so dashboard shows result
            try:
                await hass.services.async_call(
                    "input_text",
                    "set_value",
                    {
                        "entity_id": "input_text.swedavia_search_flight",
                        "value": flight_id,
                    },
                )
            except Exception:
                pass
        else:
            _LOGGER.info("Swedavia search: %s not found today", flight_id)
            hass.bus.async_fire(
                "swedavia_flight_not_found",
                {"flight_id": flight_id},
            )

    return handle


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload Swedavia config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok


async def _async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload when options change – merge options into data so UI stays consistent."""
    if entry.options:
        updated_data = {**entry.data}
        for key in (CONF_AIRPORTS, CONF_FLIGHTINFO_INTERVAL, CONF_WAITTIME_INTERVAL):
            if key in entry.options:
                updated_data[key] = entry.options[key]
        hass.config_entries.async_update_entry(entry, data=updated_data, options={})
    await hass.config_entries.async_reload(entry.entry_id)


