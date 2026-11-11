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
  - Switches: Power, Quiet Fan, Swing Mode, Comfort Airflow, Econo, Outdoor Unit Quiet, Powerful
  - Select: HVAC Mode Fan Speed, Swing Mode

  - Sensors: Outdoor temperature, energy today, runtime today indoor temp, humidity
  - Sensor: Target temperature (Not programming only, not in UI, Null if not applicable due to HVAC Mode)

### Post-off drying (mold proof)

Daikin units run a "MOLD PROOF" internal-clean cycle (about 60 minutes of
drying airflow) after COOL or DRY operation ends, but the official manuals
state it is **skipped when the unit is turned off via a timer or a
smartphone**. The integration offers an opt-in **post-off drying** option to
compensate (open the integration entry, then *Options*): *Post-off drying
(mold proof)* toggle and *Drying duration (minutes)* (5-180, default 60; a
change applies from the next cycle).

How it works:

- After a COOL or DRY operation is switched off, the integration checks the
  source the unit reports for its last operation.
  - **IR remote**: skipped, the unit is expected to run its own MOLD PROOF
    cycle (see the limitations below).
  - **Home Assistant, Daikin app, OFF TIMER, or unknown source**: the unit is
    switched to fan-only for the configured duration, then powered off. An
    OFF TIMER off is detected by the unit's off-timer having 1-2 minutes left.
- Fan speed: shortly after fan-only starts (a separate request on a later poll)
  the fan-only fan speed is set to Auto. The unit's remembered fan-only speed
  is not restored afterwards. Swing is not changed.
- Timing: the drying starts on the first poll at least 30 seconds after the
  off is seen (typically about a minute).
- Drying is cancelled (or handed over) if the unit is switched off or changed
  to another mode from any source, or if the remote or app operates it during
  drying (the fan keeps running and you switch it off yourself). An accepted
  Home Assistant climate action during drying (fan speed, swing, mode,
  temperature, on/off) hands the unit back to you.
- The sensor **Daikin Post-off Drying End (<ip>)** shows the end time while
  drying, and is unknown otherwise.
- Drying survives a Home Assistant restart, reload, or options save: it
  resumes, or powers the unit off if the end time already passed. Removing the
  integration entry mid-drying powers the unit off. Disabling the integration
  entry mid-drying leaves the unit blowing until the entry is re-enabled or the
  unit is switched off.

Limitations and risks:

- The unit's own MOLD PROOF cycle after an IR-remote off only runs after the
  unit has operated long enough. On the unit used for testing, about 4 minutes of
  cooling before a remote off did not start it; the real threshold is
  unknown. After a short run switched off with the remote, neither the unit
  nor this integration dries.
- After a drying cycle the unit is switched off while still in fan-only mode,
  and it remembers that mode. Turning it on with a power-only command (the
  Home Assistant Power switch; the Daikin app was not tested) starts it in
  fan-only mode, not in the mode it had before. Select the mode from the climate
  entity (or use the remote) to start cooling again.
- If Home Assistant is down or unreachable across the end time, the
  integration files are deleted without removing the entry, or a storage write
  fails, the unit keeps blowing until you switch it off.
- The waiting phase (between the off and the start of drying, about 30-90
  seconds) is not stored: a Home Assistant restart or options save in that
  window skips that cycle. A start request that never reached the unit is
  retried after a restart.
- The unit reports only its last operation: e.g. a remote off followed within
  one poll by an app change causes an extra cycle on top of MOLD PROOF. A
  remote off in the last ~2 minutes of a pending OFF TIMER counts as a timer
  off.
- The 60-minute default comes from the operation manuals of same-generation
  (firmware 2.8.0) Daikin units, not from a manual specific to the
  Yokozuna (橫綱V) model.

### Feature switches (model-dependent)

- **Comfort Airflow**, **Econo**, **Outdoor Unit Quiet** and **Powerful** are exposed as
  switches when the unit's LAN adapter reports them. If your model does not expose
  a feature, the switch shows as *unknown* rather than a fake off.
- The hardware allows only one of Powerful or {Comfort Airflow, Econo, Outdoor Unit
  Quiet} at a time, so turning one on clears the other side (last button pressed wins,
  like the remote).
- Powerful is cancelled by the unit after ~20 minutes on its own; the switch will
  show as off on the next poll.

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
