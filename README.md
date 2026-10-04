# Zwolle Bezoekersparkeren

A read-only [Home Assistant](https://www.home-assistant.io/) integration that monitors
visitor-parking ("bezoekersparkeren") on the Gemeente Zwolle **Parkeerloket** portal
(DVSPortal) — <https://parkeerloket.zwolle.nl/DVSPortal/>.

It tells you, at a glance, whether a parking reservation is active right now, for which
licence plate, from when until when, and how much balance is left.

> [!IMPORTANT]
> This integration talks to an **unofficial, undocumented** API. It was reverse engineered
> from the portal's own web app and can break at any time without notice. It is not
> affiliated with or endorsed by Gemeente Zwolle.

## Features

- **Monitoring only.** No booking, extending or cancelling. A stray service call would cost
  real money, so those actions are deliberately not exposed.
- Automatic re-login when the portal session expires, and a reauthentication flow if the
  credentials stop working.
- Configurable polling interval (the portal is a shared production system, so the minimum
  is one minute and the default is five).

## Entities

One device ("Zwolle Bezoekersparkeren") with:

| Entity | Description |
| --- | --- |
| `sensor.…_saldo` | Remaining balance, in minutes (shown as hours in the UI). |
| `binary_sensor.…_parkeren_actief` | `on` while a reservation covers the current moment. |
| `sensor.…_kenteken` | Licence plate of the reservation covering now, or of the next upcoming one. |
| `sensor.…_start` | Start of that reservation. |
| `sensor.…_eind` | End of that reservation. |
| `sensor.…_zone` | Permit zone (e.g. `ZONE1`). Disabled by default. |

When no reservation exists at all, the plate sensor is `unknown` and the binary sensor is `off`.

## Installation

### HACS

1. In HACS, open **Integrations** → the three-dot menu → **Custom repositories**.
2. Add `https://github.com/Wendelstein7/ha-zwolle-bezoekersparkeren` as an **Integration**.
3. Install **Zwolle Bezoekersparkeren** and restart Home Assistant.

### Manually

Copy `custom_components/zwolle_parkeerloket` into your Home Assistant `config/custom_components`
directory and restart Home Assistant.

## Configuration

1. Go to **Settings → Devices & services → Add integration**.
2. Search for **Zwolle Bezoekersparkeren**.
3. Enter the **Meldnummer** and **Pincode** printed on your parking permit, or supplied by
   the municipality.

The credentials are stored by Home Assistant in its own configuration storage and are only
sent to the Zwolle portal. They are never sent anywhere else.

### Options

**Configure** the integration to change how often the portal is polled (1–60 minutes,
default 5).

## Troubleshooting

| Symptom | Likely cause |
| --- | --- |
| `Invalid authentication` during setup | Wrong Meldnummer/Pincode, or the permit is no longer active. |
| `Failed to connect` during setup | The portal is unreachable, or is down for maintenance. |
| Sensors stop updating, "needs reauthentication" appears | The session expired and could not be renewed, or the password changed. Reconfigure the integration. |

Enable debug logging if you need more detail:

```yaml
logger:
  default: warning
  logs:
    custom_components.zwolle_parkeerloket: debug
```

## How it talks to the portal

Authentication is cookie based: `POST api/login` with the Meldnummer and Pincode returns a
session cookie plus a CSRF token cookie, which is echoed back as an `X-XSRF-TOKEN` header.
A single `POST api/login/getbase` call then returns the balance, the active reservations and
the saved licence plates; the integration polls that one endpoint.

Notable behaviours of the portal that this integration handles:

- Session cookies are session-only, so the integration logs in again when a session expires.
- Expired sessions on `login/getbase` answer with **HTTP 500 and an HTML body** rather than
  401. The client therefore treats a 5xx with a non-JSON body as "session expired", logs in
  once more, and retries exactly one time.
- CSRF tokens rotate on every login, and the newly issued token must be re-read afterwards.
- Only one reservation can be active at a time, so the booking list is not modelled.

## Development

A virtual environment with the pinned Home Assistant release, the test harness and the linter:

```bash
uv venv --python 3.14 .venv          # or: python3 -m venv .venv
uv pip install --python .venv/bin/python -r requirements_dev.txt
.venv/bin/python -m pytest
.venv/bin/ruff check . && .venv/bin/ruff format --check .
```

To run a local Home Assistant instance that loads the integration straight from this
repository, copy the integration into the (gitignored) development config directory:

```bash
mkdir -p config/custom_components
ln -sfn ../../custom_components/zwolle_parkeerloket config/custom_components/zwolle_parkeerloket
.venv/bin/hass -c config --skip-pip
```

Then open <http://localhost:8123>. The `config/` directory is gitignored: it holds a throwaway
instance, its database and its storage, and must never contain real credentials in a commit.

The fixtures under `tests/fixtures` and the placeholders in `tests/helpers.py` are synthetic.
Never copy real credentials, licence plates or names out of a live account into this repository:
this repository is public, and the portal account belongs to a real person.

## License

[MIT](LICENSE)
