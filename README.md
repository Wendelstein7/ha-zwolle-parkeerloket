# Zwolle Bezoekersparkeren

A [Home Assistant](https://www.home-assistant.io/) integration for visitor-parking
("bezoekersparkeren") on the Gemeente Zwolle **Parkeerloket** portal (DVSPortal) —
<https://parkeerloket.zwolle.nl/DVSPortal/>.

It tells you, at a glance, whether a parking reservation is active right now, for which
licence plate, from when until when, and how much balance is left. It can also start, stop,
extend and shorten a reservation.

> [!IMPORTANT]
> This integration talks to an **unofficial, undocumented** API. It was reverse engineered
> from the portal's own web app and can break at any time without notice. It is not
> affiliated with or endorsed by Gemeente Zwolle.

> [!WARNING]
> Booking and extending **spend balance**, and the portal allows only one reservation at a
> time. The integration guards against this as much as it reasonably can — see
> [Actions](#actions) — but a booking you make is a real booking.

## Features

- Monitoring: balance, the current reservation, its plate and its window.
- Actions: book now, stop, extend and shorten, as buttons and as service actions.
- Automatic re-login when the portal session expires, and a reauthentication flow if the
  credentials stop working.
- Configurable polling interval (the portal is a shared production system, so the minimum
  is one minute and the default is five).

## Entities

One device ("Zwolle Bezoekersparkeren"), with names translated into your Home Assistant
language (Dutch or English). Entity IDs follow that language too, so they may differ from
the names below.

| Entity | Description |
| --- | --- |
| Balance | Remaining balance, in minutes (shown as hours in the UI). |
| Parking active | `on` while a reservation covers the current moment. |
| Licence plate | Plate of the reservation covering now, or of the next upcoming one. |
| Parking start | Start of that reservation. |
| Parking end | End of that reservation. |
| Zone | Permit zone (e.g. `ZONE1`). Disabled by default. |
| Licence plate to book | The plate the book button will use. See [Actions](#actions). |
| Book now | Book a parking session starting now. |
| Stop booking | Cancel the current reservation. |
| Extend by 30 minutes | Add 30 minutes to the current reservation. |
| Shorten by 30 minutes | Take 30 minutes off the current reservation. |

When no reservation exists at all, the plate sensor is `unknown` and the binary sensor is `off`.
Each button is `unavailable` when the portal would refuse the action, so the UI says "you
cannot do that right now" before you find out the hard way.

## Actions

### The licence plate field

Booking needs a licence plate, so there is a `text` entity for it. It behaves as both an
input and a mirror:

- typing sets the plate that the **Book now** button will book, normalised to the form the
  portal expects (`aa-11-bb` becomes `AA11BB`);
- when the plate the portal reports **changes** — you booked, or a booking appeared
  elsewhere — the field snaps to that value, so it always shows what is really booked;
- a plate you typed is otherwise left alone, and survives restarts, so it is still there
  next time you book.

### Buttons

| Button | What it does |
| --- | --- |
| Book now | Books the plate in the field, starting now, for the portal's own default duration. |
| Stop booking | Cancels the current reservation, refunding the minutes it had not used. |
| Extend by 30 minutes | Adds 30 minutes to the current reservation. |
| Shorten by 30 minutes | Takes 30 minutes off it, if that does not end the session first. |

Booking deliberately always creates the portal's default duration rather than a duration you
pick: sending a start time of "now" can be rejected as being in the past by the time the
portal processes it. Use the extend and shorten buttons, or the action below, to reach a
different duration.

### Service actions

Available as `zwolle_parkeerloket.<action>`, targeting the parking account (any of its
entities, or its device).

| Action | Fields | Description |
| --- | --- | --- |
| `start_booking` | `license_plate`, `force` | Books starting now. Without `license_plate` the plate field is used. |
| `stop_booking` | — | Cancels the current reservation. |
| `change_booking_time` | `minutes` | Extends (positive) or shortens (negative) the current reservation. |

### Guardrails

- **Only one reservation at a time.** `start_booking` refuses while a reservation exists,
  because a second booking spends balance. Pass `force: true` if you really mean it, and
  the **Nu boeken** button is simply unavailable.
- **Extending is blocked when the portal blocks it.** The portal names the reservations it
  will not prolong; those cannot be extended from here either.
- **Shortening cannot end a session.** A change that would move the end into the past is
  refused, which is the same rule the portal's own web app applies.
- **The bookable window is respected.** The portal publishes how far ahead you can book
  (about two months); extending beyond that is refused before asking, with a message
  explaining why.
- **Nothing happens by itself.** The integration only acts when you or an automation ask it
  to; polling never books, extends or cancels anything.
- Unavailable states and error messages aside, the portal has the last word: any rejection it
  returns is shown to you, in its own words when the reason is not one we recognise.

### Balance and cost

Extended and shortened reservation lengths are charged and refunded by the portal, not by
this integration: minutes inside a paid window cost balance, minutes in a free window do not.
Cancelling refunds what was not used, and cancelling before the start refunds everything.

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
| "A parking session already exists" when booking | The portal holds one reservation at a time. Stop it first, or pass `force: true`. |
| "No licence plate to book" | The plate field is empty. Fill it in, or pass `license_plate` to `start_booking`. |
| "is not a valid licence plate" | The plate has a typo or an unexpected shape. Letters and digits only. |
| "cannot be extended by N minutes" | The portal will not prolong this reservation, or it already ends at the furthest bookable moment. |
| "cannot be shortened by N minutes without ending it" | Shortening that far would move the end into the past. |
| An error quoting the portal in Dutch | The portal rejected the request for a reason we do not translate, so its own wording is shown verbatim. |

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
- Booking actions answer with the updated permit rather than the whole account, so the
  integration applies that response directly instead of polling again.
- Changing a reservation is a **signed number of minutes**, not a new end time. The window and
  the plate of an existing reservation cannot be changed in place.
- Booking omits the start and end dates, which makes the portal book from the current moment
  for its own default duration. A reservation can therefore only be lengthened or shortened
  afterwards, which is all the API offers anyway.
- Business errors arrive with **HTTP 200** and an `ErrorMessage` body, so a status check alone
  would report rejections as successes.

## Development

A virtual environment with the pinned Home Assistant release, the test harness and the linter:

```bash
uv venv --python 3.14 .venv          # or: python3 -m venv .venv
uv pip install --python .venv/bin/python -r requirements_dev.txt
.venv/bin/python -m pytest
.venv/bin/ruff check . && .venv/bin/ruff format --check .
```

The integration is tested against the current stable Home Assistant release and the current
beta, and CI runs both.

### Trying it in a clean Home Assistant

**With Docker** — a throwaway, fresh instance in one command, so you see the same onboarding
and setup a new user gets:

```bash
docker compose up -d        # first run may need: sudo docker compose up -d
```

Open <http://localhost:8123>, complete onboarding, then go to
**Settings → Devices & services → Add integration → Zwolle Bezoekersparkeren** and enter the
Meldnummer and Pincode. Useful commands:

```bash
docker compose logs -f homeassistant     # follow the log
docker compose down                      # stop, keep the instance
docker compose down -v                   # stop and throw it away
```

The compose file uses Home Assistant's `stable` image and mounts `custom_components`
read-only, so nothing root-owned lands in your working copy. Change the image tag to `beta`
or to an exact version such as `2026.9.4` to test a different release.

> **Snap users:** the `docker` snap starts `dockerd` with `--group docker`, but the snap
> cannot resolve a group created after it started — `getent group docker` inside the snap
> returns nothing — so `/run/docker.sock` stays `root:root` and plain `docker` gives
> "permission denied". Either prefix the commands with `sudo`, or install Docker from
> [Docker's own apt repository](https://docs.docker.com/engine/install/ubuntu/), which does
> not have this quirk.

**Without Docker** — a local Home Assistant from the development environment:

```bash
mkdir -p config/custom_components
ln -sfn ../../custom_components/zwolle_parkeerloket config/custom_components/zwolle_parkeerloket
.venv/bin/hass -c config --skip-pip
```

The `config/` directory is gitignored: it holds a throwaway instance, its database and its
storage, and must never contain real credentials in a commit. Delete its `.storage` directory
to start over from onboarding.

The fixtures under `tests/fixtures` and the placeholders in `tests/helpers.py` are synthetic.
Never copy real credentials, licence plates or names out of a live account into this repository:
this repository is public, and the portal account belongs to a real person.

## Brand assets

The icon under `custom_components/zwolle_parkeerloket/brand/` is the logo of Gemeente
Zwolle, taken from [zwolle.nl](https://www.zwolle.nl). That mark belongs to the
municipality; it is used here only to identify the portal this integration talks to, and
it implies no affiliation with or endorsement by Gemeente Zwolle. It will be replaced
with a neutral icon if the municipality objects.

## License

[MIT](LICENSE)
