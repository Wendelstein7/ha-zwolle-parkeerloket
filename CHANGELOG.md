# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- A `docker-compose.yml` for trying the integration in a throwaway, clean Home
  Assistant instance.
- CI coverage for the current stable Home Assistant release alongside the newest one.
- Action buttons to book a parking session starting now, stop it, and extend or
  shorten it by 30 minutes. Each button is unavailable when the portal would refuse
  the action, so the UI answers "can I do this?" up front.
- Service actions `start_booking`, `stop_booking` and `change_booking_time`, which
  take an explicit licence plate and an arbitrary number of minutes.
- A licence plate text entity that doubles as the plate input for the book button.
  It mirrors the plate the portal reports whenever that changes, while leaving a
  draft you typed alone, including across restarts.
- Guardrails for actions that spend balance: a second booking is refused unless
  explicitly forced, extending is blocked where the portal blocks it, shortening may
  not end a session, and the portal's bookable window is respected before asking.
- Translations for the new entities, service actions and error messages in English
  and Dutch.
- The Gemeente Zwolle logo as the integration's icon, shipped as a local brand
  directory so Home Assistant shows it without waiting for a release of the shared
  brands repository.
- Initial version monitoring a visitor-parking account on the Gemeente Zwolle
  "Parkeerloket" portal:
  - remaining balance sensor
  - binary sensor for whether a reservation is active right now
  - licence plate of the current reservation
  - start and end timestamps of the current reservation
  - zone sensor (disabled by default)
- Config flow with Meldnummer/Pincode authentication, a reauthentication flow and
  an options flow for the polling interval.

### Changed

- Actions no longer poll after a change: the portal's write responses carry the
  updated permit, which is applied directly.

### Fixed

- The licence plate field now refreshes the buttons immediately when a plate is
  typed, instead of waiting for the next poll.
