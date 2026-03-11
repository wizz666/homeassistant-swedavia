"""Constants for Swedavia integration."""

DOMAIN = "swedavia"

CONF_FLIGHTINFO_KEY = "flightinfo_api_key"
CONF_WAITTIME_KEY = "waittime_api_key"
CONF_AIRPORTS = "airports"
CONF_FLIGHTINFO_INTERVAL = "flightinfo_interval"
CONF_WAITTIME_INTERVAL = "waittime_interval"

FLIGHTINFO_BASE = "https://api.swedavia.se/flightinfo/v2"
WAITTIME_BASE = "https://api.swedavia.se/waittimepublic/v2"

# All 10 Swedavia airports
AIRPORTS: dict[str, str] = {
    "ARN": "Stockholm Arlanda",
    "GOT": "Göteborg Landvetter",
    "BMA": "Stockholm Bromma",
    "MMX": "Malmö",
    "LLA": "Luleå",
    "UME": "Umeå",
    "OSD": "Åre Östersund",
    "VBY": "Visby",
    "RNB": "Ronneby",
    "KRN": "Kiruna",
}

# Default polling intervals (minutes)
DEFAULT_FLIGHTINFO_INTERVAL = 60
DEFAULT_WAITTIME_INTERVAL = 30

# API auth header
API_KEY_HEADER = "Ocp-Apim-Subscription-Key"

# Required by FlightInfo API – without this it returns 400
API_ACCEPT_HEADER = "application/json"

# Request timeout seconds
REQUEST_TIMEOUT = 20
