"""Constants for the Zwolle Bezoekersparkeren integration."""

from typing import Final

DOMAIN: Final = "zwolle_parkeerloket"

NAME: Final = "Zwolle Bezoekersparkeren"

MANUFACTURER: Final = "Gemeente Zwolle"

# Config entry keys
CONF_MELDNUMMER: Final = "meldnummer"
CONF_PINCODE: Final = "pincode"
CONF_PERMIT_MEDIA_TYPE_ID: Final = "permit_media_type_id"

# Options keys
CONF_SCAN_INTERVAL: Final = "scan_interval"

# The Meldnummer tab of the portal's login form, which is what this integration
# authenticates with. See the API notes for the full LoginMethod enum.
PERMIT_MEDIA_TYPE_MELDNUMMER: Final = 9

DEFAULT_PERMIT_MEDIA_TYPE_ID: Final = PERMIT_MEDIA_TYPE_MELDNUMMER

# The portal is a shared production system, so stay well clear of anything that
# looks like abuse.
DEFAULT_SCAN_INTERVAL_MINUTES: Final = 5
MIN_SCAN_INTERVAL_MINUTES: Final = 1
MAX_SCAN_INTERVAL_MINUTES: Final = 60

# How much the extend and shorten buttons change a reservation by. The portal's
# own web app steps by the permit's ProlongMinutes (10 for this account); we use a
# deliberately larger, rounder step and let the service action take any value.
BOOKING_STEP_MINUTES: Final = 30

# A licence plate as typed, including separators, before it is normalised.
MAX_PLATE_INPUT_LENGTH: Final = 16

API_BASE_URL: Final = "https://parkeerloket.zwolle.nl/DVSPortal"
API_TIMEOUT_SECONDS: Final = 30
