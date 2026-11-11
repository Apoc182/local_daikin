"""Constants for the Local Daikin integration."""

DOMAIN = "local_daikin"
CONF_IP_ADDRESS = "ip_address"

# Entry option: run a fan-only drying cycle after the unit is switched off,
# mimicking the Daikin "MOLD PROOF" internal-clean that the WiFi path skips.
CONF_POST_OFF_DRYING = "post_off_drying"

# Drying duration. Matches the 60-minute MOLD PROOF duration documented in the
# official operation manuals for the same-generation (firmware 2.8.0) units.
POST_OFF_DRYING_DURATION = 60 * 60  # seconds
# Pause between sequence steps (off seen -> fan-only -> quiet). The unit resets
# its fan speed on a mode change, so each step needs time to settle. Kept below
# the 60 s poll interval so the next regular poll always passes it.
POST_OFF_DRYING_START_DELAY = 30  # seconds
