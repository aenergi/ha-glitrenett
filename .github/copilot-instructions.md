# Copilot instructions

This repository contains the `glitrenett` Home Assistant custom
integration. Follow the current Home Assistant developer documentation at
https://contributors.home-assistant.io/ and the HACS documentation at
https://hacs.xyz/ for all development and publishing conventions. In
particular, consult the Home Assistant integration guidance and
[HACS integration publishing requirements](https://hacs.xyz/docs/publish/integration/)
when changing integration code or repository structure.

- Keep the integration in `custom_components/glitrenett/` and preserve
  the domain `glitrenett`; it must match the integration directory and
  manifest.
- Follow Home Assistant conventions for integration setup, configuration,
  entities, platforms, asynchronous I/O, error handling, translations, and
  testing as applicable to the change. Prefer Home Assistant helpers and APIs
  over custom implementations.
- Keep the integration manifest valid and sorted as required by Home
  Assistant. Keep HACS repository metadata at the repository root.
- Make focused changes and add or update tests for behavior when a suitable
  test setup exists. Run the relevant checks; this repository's validation
  workflow runs HACS validation and Home Assistant `hassfest`.
