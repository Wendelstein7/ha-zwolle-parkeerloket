# Zwolle Parkeerloket

A [Home Assistant](https://www.home-assistant.io/) integration for the Gemeente Zwolle
**Parkeerloket** portal (DVSPortal) — <https://parkeerloket.zwolle.nl/DVSPortal/>.

The portal manages a parking permit, and the same account can be used to park a visitor's car
or your own, so this integration covers both.

It tells you, at a glance, whether a parking reservation is active right now, for which
licence plate, from when until when, and how much balance is left. It can also start, stop,
extend and shorten a reservation.

> [!IMPORTANT]
> This integration talks to an **unofficial, undocumented** API. It was reverse engineered
> from the portal's own web app and can break at any time without notice. It is not
> affiliated with or endorsed by Gemeente Zwolle.

> [!WARNING]
> Booking and extending **spend balance**. The integration guards against booking the same
> plate twice over the same period — the portal refuses that too — but a booking you make is
> a real booking. See [Actions](#actions).

## Features

- Monitoring: balance, how many cars are parked, and which plates they use.
- A calendar entity listing every reservation, with cancel and resize from the Calendar
  panel.
- Actions: book now, stop, extend and shorten, as buttons and as service actions.
- Automatic re-login when the portal session expires, and a reauthentication flow if the
  credentials stop working.
- Configurable polling interval (the portal is a shared production system, so the minimum
  is one minute and the default is five).

## Entities

One device ("Zwolle Parkeerloket"), with names translated into your Home Assistant
language (Dutch or English). Entity IDs follow that language too, so they may differ from
the names below.

| Entity | Description |
| --- | --- |
| Balance | Remaining balance, in minutes (shown as hours in the UI). |
| Parking active | `on` while any reservation covers the current moment. |
| Bookings | How many cars are parked right now. Every booking and its window is an attribute. |
| Licence plate | Plate of the car whose session ends soonest, or of the next upcoming one. |
| Parking calendar | Every reservation as a calendar event. See [Several cars](#several-cars). |
| Zone | Permit zone (e.g. `ZONE1`). Disabled by default. |
| Licence plate to book | The plate the book button will use. See [Actions](#actions). |
| Book now | Book a parking session starting now. |
| Stop booking | Cancel a parking session. |
| Extend by 30 minutes | Add 30 minutes to a parking session. |
| Shorten by 30 minutes | Take 30 minutes off a parking session. |

When nothing is booked, the plate sensor is `unknown`, the bookings sensor is `0` and the
binary sensor is `off`. Each button is `unavailable` when the portal would refuse the action,
so the UI says "you cannot do that right now" before you find out the hard way.

## Several cars

The portal keeps several reservations at once, so more than one car can be parked in the same
period. Three rules keep that from becoming guesswork:

- **A single-valued entity describes one car.** The licence plate sensor, and the calendar's
  current event, describe the parked car whose session **ends soonest** — the one most likely
  to need attention. The bookings sensor counts the rest, and every booking is listed in its
  attributes, so a dashboard cannot be misled by the one value it shows.
- **An action always names a licence plate.** `stop_booking` and `change_booking_time` take
  the plate of the car they should act on, rather than assuming "the" booking. That is what
  makes them safe in an automation.
- **A button steps aside when it cannot tell cars apart.** Buttons cannot take an argument,
  so they only act while exactly one booking is in play. With two cars parked, stop, extend
  and shorten go `unavailable`; the calendar and the actions above take over. Cancelling
  whichever car happened to come first would be a coin flip on somebody's session.

For per-car control from the UI, open the **Calendar** panel: each reservation is an event,
and you can cancel or resize exactly the one you picked. The event's title is the licence
plate, and its description carries the reservation id and how many minutes it charged.

## Actions

### The licence plate field

Booking needs a licence plate, so there is a `text` entity for it. It behaves as both an
input and a mirror:

- typing sets the plate that the **Book now** button will book, normalised to the form the
  portal expects (`aa-11-bb` becomes `AA11BB`);
- when the plate the entities follow **changes** — you booked, or a booking appeared
  elsewhere — the field snaps to that value, so it reflects what is really booked;
- a plate you typed is otherwise left alone, and survives restarts, so it is still there
  next time you book.

### Buttons

| Button | What it does | Available when |
| --- | --- | --- |
| Book now | Books the plate in the field, starting now, for the portal's own default duration. | A plate is in the field and it is not parked already. |
| Stop booking | Cancels the session, refunding the minutes it had not used. | Exactly one car is parked, or exactly one session is booked. |
| Extend by 30 minutes | Adds 30 minutes to the session. | As above, and the portal allows extending it. |
| Shorten by 30 minutes | Takes 30 minutes off it. | As above, and it does not end the session first. |

Booking deliberately always creates the portal's default duration rather than a duration you
pick: sending a start time of "now" can be rejected as being in the past by the time the
portal processes it. Use the extend and shorten buttons, or the action below, to reach a
different duration.

### Service actions

Available as `zwolle_parkeerloket.<action>`, targeting the parking account (any of its
entities, or its device). Every one of them requires `license_plate`:

| Action | Fields | Description |
| --- | --- | --- |
| `start_booking` | `license_plate` | Books that plate starting now. |
| `stop_booking` | `license_plate` | Cancels the session parking that plate. |
| `change_booking_time` | `license_plate`, `minutes` | Extends (positive `minutes`) or shortens (negative) the session parking that plate. |

A plate is resolved to the session that is parked now, or, if that car is not parked yet, to
its soonest upcoming session. The portal still receives a reservation id — the plate is just
what you write.

```yaml
action: zwolle_parkeerloket.stop_booking
target:
  device_id: 0f1e2d3c4b5a
data:
  license_plate: AA11BB
```

### Guardrails

- **One plate cannot park twice.** The portal refuses two overlapping reservations for the
  same plate, and so does `start_booking`, before spending a round trip on it. Another car is
  no problem: book it while the first is parked.
- **Extending is blocked when the portal blocks it.** The portal names the reservations it
  will not prolong; those cannot be extended from here either.
- **Shortening cannot end a session.** A change that would move the end into the past is
  refused, which is the same rule the portal's own web app applies.
- **The bookable window is respected.** The portal publishes how far ahead you can book
  (about two months); extending beyond that is refused before asking, with a message
  explaining why.
- **A booking cannot be moved or re-plated.** The portal only changes how long a reservation
  lasts, so dragging an event's start in the Calendar panel is refused instead of appearing
  to work.
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

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=Wendelstein7&repository=ha-zwolle-parkeerloket&category=integration)

The button adds the repository to HACS on your own instance, with the URL and category
already filled in. It does not install anything by itself: after adding it, install
**Zwolle Parkeerloket** and restart Home Assistant.

Or do it by hand:

1. In HACS, open **Integrations** → the three-dot menu → **Custom repositories**.
2. Add `https://github.com/Wendelstein7/ha-zwolle-parkeerloket` as an **Integration**.
3. Install **Zwolle Parkeerloket** and restart Home Assistant.

### Manually

Copy `custom_components/zwolle_parkeerloket` into your Home Assistant `config/custom_components`
directory and restart Home Assistant.

## Configuration

1. Go to **Settings → Devices & services → Add integration**.
2. Search for **Zwolle Parkeerloket**.
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
| "AA11BB is already parked" when booking | The portal refuses two overlapping reservations for one plate. Stop that session first, or book a different plate. |
| "No licence plate to book" | The plate field is empty, so the book button has nothing to book. Fill it in. |
| "There is no parking session for AA11BB" | That plate is not parked, so there is nothing to stop or change. Check the Bookings sensor for the plates that are. |
| Stop, extend and shorten are `unavailable` with two cars parked | Buttons cannot name a car, so they step aside. Use the Calendar panel or an action with `license_plate`. See [Several cars](#several-cars). |
| A change from the Calendar panel is refused | The portal only adjusts how long a booking lasts: moving its start or changing its plate is not possible. Cancel and book again instead. |
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
- Several reservations can be active at once, for different plates, so the booking list is
  modelled and both the sensors and the calendar entity report it.
- Booking actions answer with the updated permit rather than the whole account, so the
  integration applies that response directly instead of polling again. That permit lists
  **every** reservation, not just the one that changed, which is what makes it safe to apply
  as-is when several cars are parked.
- The portal refuses a second reservation for a plate whose booking already overlaps
  (`Result: 24`), so overlapping bookings are only possible across different plates.
- A reservation is addressed by its `ReservationID`. The calendar entity uses it as the event
  uid, which is how the Calendar panel can cancel or resize one car's booking while several
  are parked.
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
**Settings → Devices & services → Add integration → Zwolle Parkeerloket** and enter the
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

### Releasing

HACS takes the tag of the newest GitHub release as the version it offers, so a release is
what turns a commit into something users can install and upgrade to. A tag on its own is not
enough: without a release, HACS falls back to the last commit hash.

`manifest.json` and the tag must carry the same version, because HACS reports the tag while
Home Assistant displays the manifest version. So a release goes:

```bash
# 1. Cut the changelog: rename [Unreleased] to the version and the date, leave a fresh
#    empty [Unreleased] on top, and set the same version in manifest.json.
# 2. Commit that, then tag and push it:
git tag -a v0.3.0 -m "0.3.0"
git push origin main
git push origin v0.3.0
# 3. Publish the release, pasting the changelog section in as its notes:
gh release create v0.3.0 --title "0.3.0"
```

The tag has to parse as a version: `0.3.0` and `v0.3.0` are both fine, `release-0.3.0` is
not. Tag a commit on the default branch, since HACS installs the integration out of that
tag's archive.

Step 3 works without the GitHub CLI too: **Releases → Draft a new release**, choose the tag
you just pushed, and paste that changelog section in as the description.

Mark a release as a **pre-release** to use it as a beta channel — HACS hides pre-releases
from users who have not switched on beta versions for the repository.

## Brand assets

The icon under `custom_components/zwolle_parkeerloket/brand/` is the logo of Gemeente
Zwolle, taken from [zwolle.nl](https://www.zwolle.nl). That mark belongs to the
municipality; it is used here only to identify the portal this integration talks to, and
it implies no affiliation with or endorsement by Gemeente Zwolle. It will be replaced
with a neutral icon if the municipality objects.

## License

[MIT](LICENSE)
