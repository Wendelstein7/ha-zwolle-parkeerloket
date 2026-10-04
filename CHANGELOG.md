# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.2.0] - 2026-10-04

### Added

- Monitoring of a parking account on the Gemeente Zwolle "Parkeerloket" portal:
  - remaining balance sensor
  - binary sensor for whether a car is parked right now
  - licence plate of the car the account is following
  - zone sensor (disabled by default)
- Support for several cars being parked at once. The portal keeps multiple reservations as
  long as they are for different plates, which this integration previously assumed was
  impossible:
  - a **Bookings** sensor reports how many cars are parked, with every booking and its
    window as attributes;
  - the **Licence plate** sensor describes the car whose session ends soonest, and says
    whether that car is parked or only booked;
  - the stop, extend and shorten buttons become `unavailable` when more than one car is
    parked, since a button cannot name which car it means.
- A calendar entity: every reservation appears as an event, and a specific car's booking can
  be cancelled or given more or less time from the Calendar panel. The event's uid is the
  portal's reservation id.
- Action buttons to book a parking session starting now, stop it, and extend or shorten it by
  30 minutes. Each button is unavailable when the portal would refuse the action, so the UI
  answers "can I do this?" up front.
- Service actions `start_booking`, `stop_booking` and `change_booking_time`, each naming the
  car it acts on by `license_plate` and taking an arbitrary number of minutes.
- A licence plate text entity that doubles as the plate input for the book button. It mirrors
  the plate the portal reports whenever that changes, while leaving a draft you typed alone,
  including across restarts.
- Guardrails for actions that spend balance: booking a plate that is already parked over an
  overlapping period is refused, extending is blocked where the portal blocks it, shortening
  may not end a session, and the portal's bookable window is respected before asking.
- Translations for the entities, service actions and error messages in English and Dutch.
- The Gemeente Zwolle logo as the integration's icon, shipped as a local brand directory so
  Home Assistant shows it without waiting for a release of the shared brands repository.
- A `docker-compose.yml` for trying the integration in a throwaway, clean Home Assistant
  instance.
- CI coverage for the current stable Home Assistant release alongside the newest one.
- Config flow with Meldnummer/Pincode authentication, a reauthentication flow and an options
  flow for the polling interval.

### Changed

- `hacs.json` now declares Home Assistant **2026.3.0** as the minimum, so HACS refuses older
  installations instead of letting them fail to import. The code uses the parenthesis-free
  `except` form, which needs Python 3.14 — the release where Home Assistant moved to it.
- The integration and its device are called **Zwolle Parkeerloket** rather than
  "Zwolle Bezoekersparkeren": the account is just as usable for parking your own car as for a
  visitor's, so the name no longer narrows it to visitors. Entity IDs therefore start with
  `zwolle_parkeerloket` instead of `zwolle_bezoekersparkeren`.
- Actions no longer poll after a change: the portal's write responses carry the
  updated permit, which is applied directly.

### Fixed

- The licence plate field now refreshes the buttons immediately when a plate is
  typed, instead of waiting for the next poll.
