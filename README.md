# ha-glitrenett-elbits

Custom Home Assistant integration for Glitrenett's implementation of the Elbits API
in Norway.

## Status

This repository is a development skeleton only. It can be installed and loaded,
but does not contact the API or create any entities yet. Credentials and UI
configuration are not implemented.

## Installation

### HACS

1. In HACS, open **Custom repositories** from the menu.
2. Add `https://github.com/epaulsen/ha-glitrenett-elbits` with type **Integration**.
3. Find **Glitrenett Elbits** in HACS and download it.
4. Restart Home Assistant.

This is a custom repository, not a listing in HACS's default catalog.

### Manual

1. Copy `custom_components/glitrenett_elbits` into the `custom_components`
   directory inside your Home Assistant configuration directory.
2. Restart Home Assistant.

## Configuration

Add the following to Home Assistant's `configuration.yaml`, then restart:

```yaml
glitrenett_elbits:
```

No options are supported yet. There is no **Add integration** UI flow.
To disable the integration, remove the YAML entry and restart Home Assistant.

## Validation

The GitHub Actions validation workflow runs HACS repository validation and
Home Assistant's hassfest on pushes, pull requests, manual runs, and daily.
There are no runtime dependencies or project-specific tests yet.

## Support and license

Report problems or feature requests in the
[issue tracker](https://github.com/epaulsen/ha-glitrenett-elbits/issues).

Licensed under the [MIT license](LICENSE).
