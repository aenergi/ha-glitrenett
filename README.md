> **Notice:** This integrations is maintained by homeassistant-enthusiasts
> employed at Å Energi and the community on their own time. No official support
> from Glitrenett AS can be expected. Pull requests are welcome.

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

## Sensors

Each metering point has the following four sensors. Home Assistant generates
their entity IDs from the metering point's device name and the sensor name;
the keys below identify the sensor types, not fixed entity IDs.

| Sensor key | Value | Unit | Custom attributes |
| --- | --- | --- | --- |
| `current_grid_price` | The grid tariff's energy price for the current time period, from the API's `energyPrice.total`. This is the grid charge, not the electricity supplier's price. | `NOK/kWh` | `grid_tariff_hours` |
| `three_hour_average` | The metering point's API-reported `levelValue`, shown as the average of its three peak hours. The integration does not calculate this average or collect consumption readings itself. | `kWh` | None |
| `energy_level_price` | The monthly capacity charge for the metering point's current energy level, from the API's `monthlyTotal`. This is a tariff amount, not a calculated monthly bill. | `NOK/month` | None |
| `energy_level` | The current capacity level's description, from the API's `levelInfo`. | None (text) | `energy_levels` |

The current energy level is selected using the API's `currentFixedPriceLevel`
reference when available. Otherwise, the integration matches `levelValue`
against the tariff's level thresholds: the minimum is inclusive and the
maximum is exclusive.

### `grid_tariff_hours`

The `current_grid_price` sensor includes all hourly tariff periods returned
by the API for its metering point, not just the currently active period.
Each item contains:

| Field | Meaning |
| --- | --- |
| `startTime` | Start timestamp of the tariff period, inclusive. |
| `expiredAt` | End timestamp of the tariff period, exclusive. |
| `energyPrice` | The API's energy-price object, retained as returned. Its `total` field supplies the sensor's value in `NOK/kWh` when the period is active. |

The current price also updates at cached tariff-period boundaries without
making another API request.

### `energy_levels`

The `energy_level` sensor includes the tariff's available capacity levels.
Each item contains:

| Field | Meaning |
| --- | --- |
| `name` | Level description from `levelInfo`. |
| `min` | Lower threshold from `valueMin`. A null value means no lower bound when matching a level. |
| `max` | Upper threshold from `valueMax`. A null value means no upper bound when matching a level. |
| `price` | Monthly capacity charge from `monthlyTotal`, in `NOK/month`. |

Thresholds use the API's consumption scale, the same scale as `levelValue`.
Fields may be null if the API does not supply them.

### Missing data

If the API omits a metering point or a required value, the affected sensor
has no value (`unknown` in Home Assistant). Custom attributes are omitted
when their underlying lists are absent or empty. If the coordinator cannot
refresh successfully, its sensors become `unavailable`.

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
