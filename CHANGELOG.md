# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Initial, read-only version monitoring a visitor-parking account on the Gemeente
  Zwolle "Parkeerloket" portal:
  - remaining balance sensor
  - binary sensor for whether a reservation is active right now
  - licence plate of the current reservation
  - start and end timestamps of the current reservation
  - zone sensor (disabled by default)
- Config flow with Meldnummer/Pincode authentication, a reauthentication flow and
  an options flow for the polling interval.
