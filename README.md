# Local Daikin Integration
This is a full integration for Daikin air conditioners using local network access. It includes UI-based setup and supports climate control, switches, selects, and sensors.
Built quick and dirty as a bridge until we have a better solution available, this custom integration allows you to connect Daikin air conditioners, specifically those running firmware version 2.8.0, to Home Assistant. It serves as a temporary solution to ensure compatibility until the official Home Assistant team can address the issue.

## 🔧 Installation

1. Copy the `local_daikin` folder into your Home Assistant `custom_components` directory:
   ```
   <config>/custom_components/local_daikin/
   ```

2. Restart Home Assistant.

3. Go to:
   **Settings → Devices & Services → Add Integration → Local Daikin**

4. Enter the IP address of your Daikin air conditioner.

The integration also provides a page-based reconfiguration flow. Open the
Local Daikin integration from **Settings → Devices & Services**, open the
entry menu, and choose **Reconfigure** to update an adapter IP without editing
Home Assistant storage files or removing the integration.

To discover multiple adapters at once, choose **Add Integration → Local
Daikin → Scan the local network**. The scan defaults to the Home Assistant
host's local `/24` network, verifies each candidate with the Daikin DSIOT API,
and adds only devices that are not already configured. The result reports
partial failures instead of treating one successful device as a complete
scan. A custom IPv4 network such as `192.168.31.0/24` can be entered when the
default network is not available.

Manual setup and reconfiguration also verify the DSIOT endpoint before saving.
The integration uses the adapter MAC address as the stable config entry ID and
gradually migrates older IP-based entries whenever the adapter is reachable.
Only IPv4 is currently supported by the integration.

The configuration pages are available in English and Traditional Chinese and
follow the language selected for the Home Assistant user account. This covers
manual setup, reconfiguration, network scanning, validation errors, and scan
results.

## Features

- Full climate control (temperature, HVAC mode, fan, swing)
- Extra entities:
  - Switches: Power, Quiet Fan, Swing Mode
  - Select: HVAC Mode Fan Speed, Swing Mode

  - Sensors: Outdoor temperature, energy today, runtime today indoor temp, humidity
  - Sensor: Target temperature (Not programming only, not in UI, Null if not applicable due to HVAC Mode)

### Post-off drying (mold proof)

Daikin units run a "MOLD PROOF" internal-clean cycle (about 60 minutes of
drying airflow) after COOL or DRY operation ends. The unit only runs it when
switched off by the remote: the official manuals state the cycle is **skipped
when the unit is turned off via a timer or a smartphone**, so switching off
from Home Assistant does not trigger it.

To compensate, the integration offers an opt-in **post-off drying** option
(open the integration entry → *Options*). When enabled, after the unit is
switched off **from Home Assistant** (not from the remote or app) while in
COOL or DRY, Home Assistant turns the unit back into a fan-only (quiet fan)
operation for **60 minutes** and powers it off again — drying the evaporator
much like the built-in cycle.

- If you switch the unit off with the **remote**, the unit runs its own
  MOLD PROOF cycle and the sequence is skipped. The API cannot tell the two
  off events apart, but the integration knows whether *it* sent the off, so
  it only compensates for the cases where the built-in cycle is actually
  skipped.
- Limitation: switching the unit off from the **Daikin app** also skips the
  built-in cycle, but an app off is indistinguishable from a remote off —
  the sequence is skipped there too. If you want the drying sequence
  guaranteed, switch the unit off from Home Assistant.
- The sequence is cancelled automatically if you switch the unit on (or
  change its mode) during the 60 minutes.
- Timing note: state changes are confirmed by the 60-second poll, so the
  drying cycle starts up to ~2 minutes after the off command and ends within
  ~1 minute after the 60 minutes elapse.
- The 60-minute duration matches the MOLD PROOF duration documented in the
  official operation manuals for the same-generation (firmware 2.8.0) Daikin
  units.

## Notes
- If upgrading from v0.0.5 (or earlier), you will need to delete the manual configuration in your `configuration.yaml` and reconfigure via the Home Assistant devices panel.
- Ensure your Daikin unit is on the same network as Home Assistant.
- Communicates with the `/dsiot/multireq` endpoint on your device.


# Compatibility
This integration has been tested and confirmed to work with the following Daikin models:
  - FTKM20YVMA with firmware version 2.8.0.
  - FTXM46WVMA with firmware version 2.8.0.

Compatibility with other models or firmware versions is not guaranteed. I keep my own units on firmware 2.8.0 and haven’t upgraded because I don’t want to risk breaking anything.

# Feedback and Contributions
This integration is a quick and dirty fix, and any suggestions for improvements or expansions are welcome. If you encounter issues or have ideas for enhancements, please open an issue in the GitHub repository for this project.

# Disclaimer
This integration is not officially supported by Home Assistant or Daikin. Use it at your own risk. The creators of this integration are not responsible for any issues that may arise from its use.
This README template should help users understand how to install, configure, and use the integration, as well as set the right expectations regarding its temporary nature and supported models. If there are any other specifics or additional sections you'd like to include, feel free to let me know!
