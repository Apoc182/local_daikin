"""Constants for the Local Daikin integration."""

DOMAIN = "local_daikin"
CONF_IP_ADDRESS = "ip_address"

# Entry option: run a fan-only drying cycle after the unit is switched off,
# mimicking the Daikin "MOLD PROOF" internal-clean that the WiFi path skips.
CONF_POST_OFF_DRYING = "post_off_drying"

# Drying duration. Matches the 60-minute MOLD PROOF duration documented in the
# official operation manuals for the same-generation (firmware 2.8.0) units.
POST_OFF_DRYING_DURATION = 60 * 60  # seconds
