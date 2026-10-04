# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.0.1] - 2026-10-04

- Declare `"country": "NL"` in `hacs.json`, marking the integration as Dutch only. HACS needs
  this before it can list a country-specific integration in its default store.

## [1.0.0] - 2026-10-04

First release: monitor and control parking reservations on the Gemeente Zwolle
"Parkeerloket" portal.

- Sensors for the balance, whether a car is parked, how many cars are parked (with every
  booking and its window as attributes), the licence plate the account follows, and the permit
  zone (disabled by default).
- A calendar entity: every reservation as an event, so one car's booking can be cancelled or
  given more or less time from the Calendar panel.
- Buttons to book a session starting now, stop it, and extend or shorten it by 30 minutes, each
  unavailable whenever the portal would refuse the action.
- Actions `start_booking`, `stop_booking` and `change_booking_time`, each naming the car it
  acts on by `license_plate`.
- A licence plate text entity that feeds the book button and mirrors the plate the portal
  reports, while keeping a draft you typed.
- Guardrails for actions that spend balance: no second overlapping booking for one plate,
  extending blocked where the portal blocks it, shortening never ends a session, and the
  portal's bookable window is respected before asking.
- Config flow with Meldnummer/Pincode, reauthentication, and a configurable polling interval.
- English and Dutch translations.
- Home Assistant 2026.3.0 or newer.
