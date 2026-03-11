"""Data coordinators for Swedavia FlightInfo and WaitTime APIs."""

from __future__ import annotations

import logging
from datetime import date, timedelta

import aiohttp

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    API_ACCEPT_HEADER,
    API_KEY_HEADER,
    FLIGHTINFO_BASE,
    REQUEST_TIMEOUT,
    WAITTIME_BASE,
)

_LOGGER = logging.getLogger(__name__)

_TIMEOUT = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)


def _today() -> str:
    """Return today's date as YYYY-MM-DD."""
    return date.today().strftime("%Y-%m-%d")


def _extract_flights(raw) -> list:
    """Parse flight list from various response shapes."""
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict):
        for key in ("flights", "FlightInfo", "flightInfo", "data", "items"):
            v = raw.get(key)
            if isinstance(v, list):
                return v
    return []


def _extract_checkpoints(raw) -> list:
    """Parse checkpoint list from various WaitTime response shapes."""
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict):
        for key in ("checkpoints", "Checkpoints", "waitTimes", "WaitTime", "data", "queues"):
            v = raw.get(key)
            if isinstance(v, list):
                return v
    return []


class SvedaviaFlightCoordinator(DataUpdateCoordinator):
    """Coordinator that fetches arrivals + departures for all selected airports."""

    def __init__(
        self,
        hass: HomeAssistant,
        airports: list[str],
        api_key: str,
        interval_minutes: int,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name="Swedavia FlightInfo",
            update_interval=timedelta(minutes=interval_minutes),
        )
        self.airports = airports
        self.api_key = api_key

    async def _async_update_data(self) -> dict:
        session = async_get_clientsession(self.hass)
        headers = {
            API_KEY_HEADER: self.api_key,
            "Accept": API_ACCEPT_HEADER,
        }
        today = _today()
        data: dict = {}

        for airport in self.airports:
            data[airport] = {"arrivals": [], "departures": [], "error": None}
            for direction in ("arrivals", "departures"):
                url = f"{FLIGHTINFO_BASE}/{airport}/{direction}/{today}"
                try:
                    async with session.get(
                        url, headers=headers, timeout=_TIMEOUT
                    ) as resp:
                        if resp.status == 200:
                            raw = await resp.json(content_type=None)
                            _LOGGER.debug(
                                "Swedavia FlightInfo %s %s raw keys: %s",
                                airport,
                                direction,
                                list(raw.keys()) if isinstance(raw, dict) else f"list[{len(raw)}]",
                            )
                            data[airport][direction] = _extract_flights(raw)
                        elif resp.status == 204:
                            # No content – no flights today
                            data[airport][direction] = []
                        elif resp.status in (401, 403):
                            raise UpdateFailed(
                                f"FlightInfo API key invalid (HTTP {resp.status})"
                            )
                        else:
                            body = await resp.text()
                            _LOGGER.warning(
                                "Swedavia FlightInfo %s %s: HTTP %s – %s",
                                airport,
                                direction,
                                resp.status,
                                body[:200],
                            )
                except UpdateFailed:
                    raise
                except aiohttp.ClientError as err:
                    _LOGGER.error(
                        "Swedavia FlightInfo network error %s %s: %s",
                        airport,
                        direction,
                        err,
                    )
                    data[airport]["error"] = str(err)
                except Exception as err:  # noqa: BLE001
                    _LOGGER.error(
                        "Swedavia FlightInfo unexpected error %s %s: %s",
                        airport,
                        direction,
                        err,
                    )
                    data[airport]["error"] = str(err)

        return data


class SvedaviaQueueCoordinator(DataUpdateCoordinator):
    """Coordinator that fetches security wait times for all selected airports."""

    def __init__(
        self,
        hass: HomeAssistant,
        airports: list[str],
        api_key: str,
        interval_minutes: int,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name="Swedavia WaitTime",
            update_interval=timedelta(minutes=interval_minutes),
        )
        self.airports = airports
        self.api_key = api_key

    async def _async_update_data(self) -> dict:
        session = async_get_clientsession(self.hass)
        headers = {
            API_KEY_HEADER: self.api_key,
            "Accept": API_ACCEPT_HEADER,
        }
        data: dict = {}

        for airport in self.airports:
            data[airport] = {"checkpoints": [], "error": None}
            url = f"{WAITTIME_BASE}/airports/{airport}"
            try:
                async with session.get(
                    url, headers=headers, timeout=_TIMEOUT
                ) as resp:
                    if resp.status == 200:
                        raw = await resp.json(content_type=None)
                        _LOGGER.debug(
                            "Swedavia WaitTime %s raw: %s",
                            airport,
                            str(raw)[:300],
                        )
                        data[airport]["checkpoints"] = _extract_checkpoints(raw)
                    elif resp.status == 204:
                        data[airport]["checkpoints"] = []
                    elif resp.status in (401, 403):
                        raise UpdateFailed(
                            f"WaitTime API key invalid (HTTP {resp.status})"
                        )
                    else:
                        body = await resp.text()
                        _LOGGER.warning(
                            "Swedavia WaitTime %s: HTTP %s – %s",
                            airport,
                            resp.status,
                            body[:200],
                        )
            except UpdateFailed:
                raise
            except aiohttp.ClientError as err:
                _LOGGER.error("Swedavia WaitTime network error %s: %s", airport, err)
                data[airport]["error"] = str(err)
            except Exception as err:  # noqa: BLE001
                _LOGGER.error(
                    "Swedavia WaitTime unexpected error %s: %s", airport, err
                )
                data[airport]["error"] = str(err)

        return data
