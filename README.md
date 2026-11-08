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
**Settings > Devices & services > Add integration**. Enter your Glitrenett API
key, then add a name and metering point ID for each metering point. You can
also add or remove metering points from the integration's configuration page;
the API key is shared. Each point appears as a device with sensors for the
current grid price, top-three-hours average consumption, and current energy
level and its price. The integration requests tariffs for all configured
points and refreshes each point no more often than once per hour.

Existing installations from before multi-point support must remove and add the
integration again. Their previous entity IDs and history are not migrated.

The API key is sent to `https://api.aenergi.no/Glitrenett/gridtariff/api/1`
using the `X-API-Key` header. The API provider recommends limiting requests to
once per day; the integration's hourly interval is the maximum polling rate.

## Validation

The GitHub Actions validation workflow runs integration tests, HACS repository
validation, and Home Assistant's hassfest on pushes, pull requests, manual
runs, and daily. To run the tests locally with Docker:

```shell
docker run --rm -v "$PWD:/workspace" -w /workspace \
  --entrypoint python ghcr.io/home-assistant/home-assistant:stable \
  -m unittest discover -s tests -v
```

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
