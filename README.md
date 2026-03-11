# ✈ Swedavia – Home Assistant Integration

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![GitHub Release](https://img.shields.io/github/release/wizz666/homeassistant-swedavia.svg)](https://github.com/wizz666/homeassistant-swedavia/releases)
[![Ko-fi](https://img.shields.io/badge/Ko--fi-Stöd_projektet-F16061?logo=ko-fi&logoColor=white)](https://ko-fi.com/wizz666)

Flyginformation och säkerhetskötider för alla 10 Swedavia-flygplatser direkt i Home Assistant.

Integrationen hämtar data från **Swedavias officiella API** och skapar sensorer för avgångar, ankomster och säkerhetskö per flygplats.

---

## Flygplatser som stöds

| Kod | Flygplats |
|-----|-----------|
| ARN | Stockholm Arlanda |
| GOT | Göteborg Landvetter |
| BMA | Stockholm Bromma |
| MMX | Malmö Airport |
| LLA | Luleå Airport |
| UME | Umeå Airport |
| OSD | Åre Östersund |
| VBY | Visby Airport |
| RNB | Ronneby Airport |
| KRN | Kiruna Airport |

---

## Sensorer (per flygplats)

| Sensor | Beskrivning |
|--------|-------------|
| `sensor.swedavia_{iata}_next_departure` | Nästa avgång, t.ex. `SK1234 → LHR 14:30` |
| `sensor.swedavia_{iata}_next_arrival` | Nästa ankomst, t.ex. `SK5678 ← CPH 15:45` |
| `sensor.swedavia_{iata}_departures_today` | Antal avgångar idag (med `upcoming_flights`-attribut) |
| `sensor.swedavia_{iata}_arrivals_today` | Antal ankomster idag (med `upcoming_flights`-attribut) |
| `sensor.swedavia_{iata}_security_wait` | Säkerhetskötid i minuter |

---

## Installation

### Krav
Du behöver API-nycklar från [Swedavia API Developer Portal](https://apideveloper.swedavia.se/):
- **FlightInfo v2** – för avgångar och ankomster
- **WaitTime Public v2** – för säkerhetskötider

Gratis-tier: 10 000 anrop/månad per API.

### Via HACS (rekommenderat)
1. Öppna HACS → Integrations → ⋮ → Custom repositories
2. Lägg till `https://github.com/wizz666/homeassistant-swedavia` (kategori: Integration)
3. Installera **Swedavia**
4. Starta om Home Assistant
5. Gå till **Inställningar → Enheter & tjänster → Lägg till integration → Swedavia**

### Manuellt
Kopiera mappen `custom_components/swedavia/` till din HA-konfigurationsmapp och starta om.

---

## Dashboard (FIDS-visning)

Inkluderar en dashboard i klassisk flygplatstavia-stil (FIDS) med:
- 🛫 **Avgångstavla** – Tid, Flygnr, Destination, Status, Gate
- 🛬 **Ankomsttavla** – Tid, Flygnr, Från, Status, Bagageband
- 🔍 **Flygsökning** – Sök på specifikt flygnummer

Kopiera filerna till din HA-konfiguration:
- `packages/swedavia.yaml` → `/config/packages/`
- `dashboards/swedavia.yaml` → `/config/dashboards/`

Lägg till i `configuration.yaml`:
```yaml
homeassistant:
  packages: !include_dir_named packages

lovelace:
  dashboards:
    swedavia-dashboard:
      mode: yaml
      filename: dashboards/swedavia.yaml
      title: "Flyginfo"
      icon: mdi:airplane-takeoff
      show_in_sidebar: true
```

---

## Rate limit

| Konfiguration | Anrop/månad (FlightInfo) |
|---------------|--------------------------|
| 1 flygplats, 60 min | ~1 440 |
| 5 flygplatser, 60 min | ~7 200 |
| 10 flygplatser, 60 min | ~14 400 ⚠️ |

Rekommendation: välj ≤ 7 flygplatser **eller** öka intervallet till ≥ 72 min.

---

## Stöd projektet

Gillar du integrationen? En kopp kaffe uppskattas ☕

[![ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/wizz666)

---

## Licens

MIT License
