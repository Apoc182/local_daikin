"""Constants for the Local Daikin integration."""

DOMAIN = "local_daikin"
CONF_IP_ADDRESS = "ip_address"

# Entry option: run a fan-only drying cycle after the unit is switched off,
# mimicking the Daikin "MOLD PROOF" internal-clean that the WiFi path skips.
CONF_POST_OFF_DRYING = "post_off_drying"

# Drying duration option (minutes). The default matches the 60-minute MOLD
# PROOF duration documented in the official operation manuals for the
# same-generation (firmware 2.8.0) units.
CONF_POST_OFF_DRYING_MINUTES = "post_off_drying_minutes"
POST_OFF_DRYING_DEFAULT_MINUTES = 60
POST_OFF_DRYING_MIN_MINUTES = 5
POST_OFF_DRYING_MAX_MINUTES = 180
# Pause between the off being seen and the source decision / fan-only start.
# The unit's last_ope lags the off by ~6 s; kept below the 60 s poll interval
# so the next regular poll always passes it.
POST_OFF_DRYING_START_DELAY = 30  # seconds

# last_ope/type values reported by the unit (200 = app, anything else unknown).
LAST_OPE_REMOTE = 1
LAST_OPE_LOCAL = 100
# An OFF TIMER reports the remote source (1); an off within this many minutes
# of the timer running out is treated as a timer off, not a remote off.
OFF_TIMER_WINDOW_MINUTES = 2
