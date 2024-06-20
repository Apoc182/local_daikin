# Local Daikin Integration
Built quick and dirty as a bridge until we have a better solution available, this custom integration allows you to connect Daikin air conditioners, specifically those running firmware version 2.8.0, to Home Assistant. It serves as a temporary solution to ensure compatibility until the official Home Assistant team can address the issue.

# Installation
To install this integration, use the Home Assistant Community Store (HACS).

# Configuration
After installation, add the integration using the IP address of your Daikin air conditioner:

```yaml
climate:
  - platform: local_daikin
    ip_address: X.X.X.Y
```

Alternatively, if you have mutliple appliances.

```yaml
climate:
  - platform: local_daikin
    ip_address:
      - X.X.X.Y
      - X.X.X.Z
      ...
```

# Compatibility
This integration has been tested and confirmed to work with the following Daikin models:
  - FTKM20YVMA with firmware version 2.8.0.
  -   - FTXM46WVMA with firmware version 2.8.0.

Compatibility with other models or firmware versions is not guaranteed.

# Feedback and Contributions
This integration is a quick and dirty fix, and any suggestions for improvements or expansions are welcome. If you encounter issues or have ideas for enhancements, please open an issue in the GitHub repository for this project.

# Disclaimer
This integration is not officially supported by Home Assistant or Daikin. Use it at your own risk. The creators of this integration are not responsible for any issues that may arise from its use.
This README template should help users understand how to install, configure, and use the integration, as well as set the right expectations regarding its temporary nature and supported models. If there are any other specifics or additional sections you'd like to include, feel free to let me know!
