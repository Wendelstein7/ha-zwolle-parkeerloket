# Zwolle Parkeerloket

A [Home Assistant](https://www.home-assistant.io/) integration for the Gemeente Zwolle
**Parkeerloket** portal (DVSPortal) — <https://parkeerloket.zwolle.nl/DVSPortal/>.

The portal manages a parking permit, and the same account can be used to park a visitor's car
or your own. The integration reports what is parked, for which plate, from when until when, and
how much balance is left — and can book, extend or cancel it.

> [!IMPORTANT]
> This integration talks to an **unofficial, undocumented** API. It was reverse engineered
> from the portal's own web app and can break at any time without notice. It is not
> affiliated with or endorsed by Gemeente Zwolle.

> [!WARNING]
> Booking and extending **spend balance**. The integration guards against booking the same
> plate twice over the same period — the portal refuses that too — but a booking you make is
> a real booking. See [Actions](#actions).

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=Wendelstein7&repository=ha-zwolle-parkeerloket&category=integration)

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
binary sensor is `off`.

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

| Button | What it does |
| --- | --- |
| Book now | Books the plate in the field, starting now, for the portal's own default duration. |
| Stop booking | Cancels the session, refunding the minutes it had not used. |
| Extend by 30 minutes | Adds 30 minutes to the session. |
| Shorten by 30 minutes | Takes 30 minutes off it. |

A button is unavailable whenever the portal would refuse the action, so the UI answers "can I
do this?" before you find out the hard way.

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
- **Costs are the portal's, not ours.** Minutes inside a paid window cost balance and minutes
  in a free window do not, so extending and shortening charge and refund accordingly.
  Cancelling refunds what was not used, and cancelling before the start refunds everything.
- Unavailable states and error messages aside, the portal has the last word: any rejection it
  returns is shown to you, in its own words when the reason is not one we recognise.

## Installation

### HACS

Use the **Add to HACS** button at the top of this page, then install **Zwolle Parkeerloket** and
restart Home Assistant. By hand instead: add
`https://github.com/Wendelstein7/ha-zwolle-parkeerloket` under **Integrations → ⋮ → Custom
repositories**, as an **Integration**.

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
| "cannot be extended" or "cannot be shortened" | The portal will not prolong that reservation, it already ends at the furthest bookable moment, or shortening it would move the end into the past. See [Guardrails](#guardrails). |
| An error quoting the portal in Dutch | The portal rejected the request for a reason we do not translate, so its own wording is shown verbatim. |

Enable debug logging if you need more detail:

```yaml
logger:
  default: warning
  logs:
    custom_components.zwolle_parkeerloket: debug
```

## How it talks to the portal

Login is cookie based, and a single `login/getbase` call returns the balance, the reservations
and the saved plates — that is the only endpoint polled. A few portal behaviours shape the
integration:

- An expired session answers `login/getbase` with **HTTP 500 and an HTML body** rather than
  401, so the client logs in again and retries exactly once.
- Several reservations can be active at once for different plates, but a second one for a plate
  that already overlaps is refused (`Result: 24`).
- A reservation is addressed by its `ReservationID`, and a change is a **signed number of
  minutes**: the window and the plate cannot be changed in place. That is why the Calendar
  panel can resize a booking but not move it.
- Booking omits the start and end dates, so the portal books from the current moment for its own
  default duration. Business errors arrive with **HTTP 200** and an `ErrorMessage` body, so a
  status check alone would report a rejection as a success.

## Development

Contributor setup, how to try it in a clean Home Assistant, and the release process live in
[CONTRIBUTING.md](CONTRIBUTING.md).

## Brand assets

The icon under `custom_components/zwolle_parkeerloket/brand/` is the logo of Gemeente
Zwolle, taken from [zwolle.nl](https://www.zwolle.nl). That mark belongs to the
municipality; it is used here only to identify the portal this integration talks to, and
it implies no affiliation with or endorsement by Gemeente Zwolle. It will be replaced
with a neutral icon if the municipality objects.

## License

[MIT](LICENSE)
