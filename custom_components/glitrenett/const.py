"""Constants for the Glitrenett integration."""

CONF_METERING_POINT_ID = "metering_point_id"
SUBENTRY_METERING_POINT = "metering_point"

# https://github.com/cgrette/API-nettleie-for-styring/blob/patch-1/doc/DiginGridTariffAPI.gridcompany-mapping.json
METERING_POINT_RANGES = (
    ("70705750007619000", "70705750008018999"),
    ("70705750004571000", "70705750004609999"),
    ("70705750002270000", "70705750002349999"),
    ("70705750001221000", "70705750001260999"),
    ("70705750008191000", "70705750008215999"),
    ("70705750008220000", "70705750008244999"),
)
