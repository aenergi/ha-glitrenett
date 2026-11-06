# ha-glitrenett

Custom Home Assistant integration for Glitrenett in Norway.

## Installation

### HACS

1. In HACS, open **Custom repositories** from the menu.
2. Add `https://github.com/epaulsen/ha-glitrenett` with type **Integration**.
3. Find **Glitrenett** in HACS and download it.
4. Restart Home Assistant.

This is a custom repository, not a listing in HACS's default catalog.

### Manual

1. Copy `custom_components/glitrenett` into the `custom_components`
   directory inside your Home Assistant configuration directory.
2. Restart Home Assistant.

## Configuration

After restarting Home Assistant, add **Glitrenett** from
**Settings > Devices & services > Add integration**. Enter the API key issued
for the Glitrenett API and the metering point ID associated with your account.
The integration checks these values with the API during setup.
The integration creates sensors for the current grid price, the top-three-hours
average consumption, and the current energy level and its price. It requests
today's tariffs and refreshes no more often than once per hour.

The API key is sent to `https://api.aenergi.no/Glitrenett/gridtariff/api/1`
using the `X-API-Key` header. The API provider recommends limiting requests to
once per day; the integration's hourly interval is the maximum polling rate.

## Validation

The GitHub Actions validation workflow runs HACS repository validation and
Home Assistant's hassfest on pushes, pull requests, manual runs, and daily.

## Development

The repository includes a VS Code Dev Container for debugging Home Assistant
with the integration mounted directly from the workspace. Install Docker and
the VS Code Dev Containers extension, open the repository in VS Code, and
choose **Reopen in Container**. Select the **Home Assistant** launch
configuration and press **F5** to start Home Assistant under the debugger.
Home Assistant is available at `http://localhost:8123`; complete onboarding
and add **Glitrenett** from **Settings > Devices & services > Add
integration**. The development config enables debug logging for this
integration. Changes to its files are visible inside Home Assistant; restart
the debug session to load code changes.

## Support and license

Report problems or feature requests in the
[issue tracker](https://github.com/epaulsen/ha-glitrenett/issues).

Licensed under the [MIT license](LICENSE).
