"""Config flow for Swedavia integration."""

from __future__ import annotations

import logging
from datetime import date

import aiohttp
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .const import (
    API_ACCEPT_HEADER,
    API_KEY_HEADER,
    AIRPORTS,
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

_LOGGER = logging.getLogger(__name__)

_AIRPORT_OPTIONS = [
    {"value": k, "label": f"{k} – {v}"} for k, v in AIRPORTS.items()
]

_INTERVAL_SELECTOR_FLIGHT = NumberSelector(
    NumberSelectorConfig(min=15, max=1440, step=15, mode=NumberSelectorMode.BOX)
)
_INTERVAL_SELECTOR_WAIT = NumberSelector(
    NumberSelectorConfig(min=5, max=720, step=5, mode=NumberSelectorMode.BOX)
)
_AIRPORT_SELECTOR = SelectSelector(
    SelectSelectorConfig(
        options=_AIRPORT_OPTIONS,
        multiple=True,
        mode=SelectSelectorMode.LIST,
    )
)


async def _test_flightinfo_key(hass, key: str) -> str | None:
    """Return error key on failure, None on success."""
    session = async_get_clientsession(hass)
    today = date.today().strftime("%Y-%m-%d")
    url = f"{FLIGHTINFO_BASE}/ARN/arrivals/{today}"
    try:
        async with session.get(
            url,
            headers={API_KEY_HEADER: key, "Accept": API_ACCEPT_HEADER},
            timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
        ) as resp:
            if resp.status in (401, 403):
                return "invalid_auth"
            if resp.status not in (200, 204):
                _LOGGER.debug("FlightInfo test HTTP %s", resp.status)
                return "cannot_connect"
    except aiohttp.ClientError:
        return "cannot_connect"
    except Exception:
        return "unknown"
    return None


async def _test_waittime_key(hass, key: str) -> str | None:
    """Return error key on failure, None on success."""
    session = async_get_clientsession(hass)
    url = f"{WAITTIME_BASE}/airports/ARN"
    try:
        async with session.get(
            url,
            headers={API_KEY_HEADER: key, "Accept": API_ACCEPT_HEADER},
            timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
        ) as resp:
            if resp.status in (401, 403):
                return "invalid_auth"
            if resp.status not in (200, 204):
                _LOGGER.debug("WaitTime test HTTP %s", resp.status)
                return "cannot_connect"
    except aiohttp.ClientError:
        return "cannot_connect"
    except Exception:
        return "unknown"
    return None


class SvedaviaConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the initial config flow."""

    VERSION = 1

    @staticmethod
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> SvedaviaOptionsFlow:
        """Return the options flow handler."""
        return SvedaviaOptionsFlow()

    async def async_step_user(self, user_input=None):
        errors: dict[str, str] = {}

        if user_input is not None:
            fi_key = user_input[CONF_FLIGHTINFO_KEY].strip()
            wt_key = user_input[CONF_WAITTIME_KEY].strip()
            airports = user_input[CONF_AIRPORTS]

            if not airports:
                errors[CONF_AIRPORTS] = "no_airports"
            else:
                err = await _test_flightinfo_key(self.hass, fi_key)
                if err:
                    errors[CONF_FLIGHTINFO_KEY] = err
                else:
                    err = await _test_waittime_key(self.hass, wt_key)
                    if err:
                        errors[CONF_WAITTIME_KEY] = err

            if not errors:
                return self.async_create_entry(
                    title="Swedavia",
                    data={
                        CONF_FLIGHTINFO_KEY: fi_key,
                        CONF_WAITTIME_KEY: wt_key,
                        CONF_AIRPORTS: airports,
                        CONF_FLIGHTINFO_INTERVAL: int(
                            user_input.get(CONF_FLIGHTINFO_INTERVAL, DEFAULT_FLIGHTINFO_INTERVAL)
                        ),
                        CONF_WAITTIME_INTERVAL: int(
                            user_input.get(CONF_WAITTIME_INTERVAL, DEFAULT_WAITTIME_INTERVAL)
                        ),
                    },
                )

        schema = vol.Schema(
            {
                vol.Required(CONF_FLIGHTINFO_KEY): str,
                vol.Required(CONF_WAITTIME_KEY): str,
                vol.Required(CONF_AIRPORTS): _AIRPORT_SELECTOR,
                vol.Optional(
                    CONF_FLIGHTINFO_INTERVAL, default=DEFAULT_FLIGHTINFO_INTERVAL
                ): _INTERVAL_SELECTOR_FLIGHT,
                vol.Optional(
                    CONF_WAITTIME_INTERVAL, default=DEFAULT_WAITTIME_INTERVAL
                ): _INTERVAL_SELECTOR_WAIT,
            }
        )

        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
        )


class SvedaviaOptionsFlow(config_entries.OptionsFlow):
    """Allow changing airports and intervals after setup."""

    async def async_step_init(self, user_input=None):
        errors: dict[str, str] = {}

        if user_input is not None:
            airports = user_input.get(CONF_AIRPORTS, [])
            if not airports:
                errors[CONF_AIRPORTS] = "no_airports"
            else:
                return self.async_create_entry(
                    title="",
                    data={
                        CONF_AIRPORTS: airports,
                        CONF_FLIGHTINFO_INTERVAL: int(
                            user_input.get(CONF_FLIGHTINFO_INTERVAL, DEFAULT_FLIGHTINFO_INTERVAL)
                        ),
                        CONF_WAITTIME_INTERVAL: int(
                            user_input.get(CONF_WAITTIME_INTERVAL, DEFAULT_WAITTIME_INTERVAL)
                        ),
                    },
                )

        entry = self.config_entry
        current_airports = entry.options.get(
            CONF_AIRPORTS, entry.data.get(CONF_AIRPORTS, [])
        )
        current_fi = entry.options.get(
            CONF_FLIGHTINFO_INTERVAL,
            entry.data.get(CONF_FLIGHTINFO_INTERVAL, DEFAULT_FLIGHTINFO_INTERVAL),
        )
        current_wt = entry.options.get(
            CONF_WAITTIME_INTERVAL,
            entry.data.get(CONF_WAITTIME_INTERVAL, DEFAULT_WAITTIME_INTERVAL),
        )

        schema = vol.Schema(
            {
                vol.Required(CONF_AIRPORTS, default=current_airports): _AIRPORT_SELECTOR,
                vol.Optional(CONF_FLIGHTINFO_INTERVAL, default=current_fi): _INTERVAL_SELECTOR_FLIGHT,
                vol.Optional(CONF_WAITTIME_INTERVAL, default=current_wt): _INTERVAL_SELECTOR_WAIT,
            }
        )

        return self.async_show_form(
            step_id="init",
            data_schema=schema,
            errors=errors,
        )
