"""Tests for multiple Glitrenett metering points."""

import asyncio
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.const import CONF_API_KEY
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers.translation import async_get_translations
from homeassistant.helpers.update_coordinator import UpdateFailed
from homeassistant.loader import Integration, async_setup

from custom_components.glitrenett import _async_reload_entry
from custom_components.glitrenett.config_flow import (
    GlitrenettConfigFlow,
    GlitrenettMeteringPointFlow,
    _validate_point,
)
from custom_components.glitrenett.coordinator import (
    APIError,
    RequestThrottled,
    _index_metering_points,
    async_get_tariffs,
)
from custom_components.glitrenett.sensor import GlitrenettSensor, async_setup_entry


def response_data():
    """Return two shared points and one point with a different tariff."""
    return {
        "gridTariffCollections": [
            {
                "gridTariff": {"name": "shared"},
                "meteringPointsAndPriceLevels": [
                    {
                        "meteringPoints": [
                            {"meteringPointId": "one", "levelValue": 1.5},
                            {"meteringPointId": "two", "levelValue": 3.5},
                        ]
                    }
                ],
            },
            {
                "gridTariff": {"name": "other"},
                "meteringPointsAndPriceLevels": [
                    {"meteringPoints": [{"meteringPointId": "three", "levelValue": 7}]}
                ],
            },
        ]
    }


class Response:
    """Mock an aiohttp response context manager."""

    def __init__(self, data, status=200):
        self.data = data
        self.status = status

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def json(self):
        return self.data

    def raise_for_status(self):
        return None


class MappingTests(unittest.TestCase):
    def test_map_shared_and_distinct_tariffs_and_point_values(self):
        indexed = _index_metering_points(response_data())
        self.assertEqual(indexed["one"]["collection"]["gridTariff"]["name"], "shared")
        self.assertEqual(indexed["two"]["point"]["levelValue"], 3.5)
        self.assertEqual(indexed["three"]["collection"]["gridTariff"]["name"], "other")
        coordinator = MagicMock()
        coordinator.data = indexed
        for point_id, expected in (("one", 1.5), ("two", 3.5), ("three", 7)):
            subentry = SimpleNamespace(
                data={"metering_point_id": point_id}, title=point_id
            )
            sensor = GlitrenettSensor(coordinator, subentry, "three_hour_average")
            self.assertEqual(sensor.native_value, expected)
            self.assertEqual(sensor.unique_id, f"{point_id}_three_hour_average")
            self.assertEqual(sensor.device_info["identifiers"], {("glitrenett", point_id)})
        missing = GlitrenettSensor(
            coordinator,
            SimpleNamespace(data={"metering_point_id": "missing"}, title="Missing"),
            "three_hour_average",
        )
        self.assertIsNone(missing.native_value)

    def test_duplicate_or_malformed_points_fail(self):
        data = response_data()
        data["gridTariffCollections"][1]["meteringPointsAndPriceLevels"][0][
            "meteringPoints"
        ][0]["meteringPointId"] = "one"
        with self.assertRaises(UpdateFailed):
            _index_metering_points(data)
        with self.assertRaises(UpdateFailed):
            _index_metering_points({"gridTariffCollections": "not a list"})

    def test_group_level_id_selects_correct_price_without_consumption(self):
        data = response_data()
        collection = data["gridTariffCollections"][0]
        collection["gridTariff"]["tariffPrice"] = {
            "priceInfo": {
                "fixedPrices": [
                    {
                        "id": "fixed",
                        "priceLevels": [
                            {"id": "low", "monthlyTotal": 100},
                            {"id": "high", "monthlyTotal": 200},
                        ],
                    }
                ]
            }
        }
        group = collection["meteringPointsAndPriceLevels"][0]
        group["currentFixedPriceLevel"] = {"id": "fixed", "levelId": "high"}
        group["meteringPoints"][0]["levelValue"] = None
        coordinator = MagicMock()
        coordinator.data = _index_metering_points(data)
        subentry = SimpleNamespace(data={"metering_point_id": "one"}, title="House")
        sensor = GlitrenettSensor(coordinator, subentry, "energy_level_price")
        self.assertEqual(sensor.native_value, 200)


class RequestTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.hass = SimpleNamespace(data={})
        self.session = MagicMock()
        self.session.post.return_value = Response(response_data())
        self.session_patch = patch(
            "custom_components.glitrenett.coordinator.async_get_clientsession",
            return_value=self.session,
        )
        self.session_patch.start()
        self.addCleanup(self.session_patch.stop)

    async def test_batch_cache_addition_and_expiry(self):
        result = await async_get_tariffs(self.hass, "key", ["one", "two"])
        self.assertEqual(set(result), {"one", "two"})
        self.assertEqual(
            self.session.post.call_args.kwargs["json"]["meteringPointIds"],
            ["one", "two"],
        )
        await async_get_tariffs(self.hass, "key", ["one", "two"])
        self.assertEqual(self.session.post.call_count, 1)

        result = await async_get_tariffs(self.hass, "key", ["one", "two", "three"])
        self.assertEqual(set(result), {"one", "two", "three"})
        self.assertEqual(
            self.session.post.call_args.kwargs["json"]["meteringPointIds"], ["three"]
        )
        cache = next(iter(self.hass.data.values()))
        for state in cache.states.values():
            state.last_request -= 3601
        await async_get_tariffs(self.hass, "key", ["one", "two", "three"])
        self.assertEqual(
            self.session.post.call_args.kwargs["json"]["meteringPointIds"],
            ["one", "two", "three"],
        )

    async def test_omitted_points_and_changed_credentials(self):
        result = await async_get_tariffs(self.hass, "key", ["one", "missing"])
        self.assertEqual(set(result), {"one"})
        self.assertEqual(await async_get_tariffs(self.hass, "key", ["missing"]), {})
        with self.assertRaises(RequestThrottled):
            await async_get_tariffs(self.hass, "other-key", ["one"])
        self.assertEqual(self.session.post.call_count, 1)

    async def test_concurrent_requests_share_cache(self):
        await asyncio.gather(
            async_get_tariffs(self.hass, "key", ["one", "two"]),
            async_get_tariffs(self.hass, "key", ["one", "two"]),
        )
        self.assertEqual(self.session.post.call_count, 1)

    async def test_304_requires_matching_cache(self):
        self.session.post.return_value = Response(None, status=304)
        with self.assertRaises(UpdateFailed):
            await async_get_tariffs(self.hass, "key", ["one"])
        self.hass.data.clear()
        self.session.post.return_value = Response(response_data())
        await async_get_tariffs(self.hass, "key", ["one"])
        cache = next(iter(self.hass.data.values()))
        cache.states["one"].last_request -= 3601
        self.session.post.return_value = Response(None, status=304)
        self.assertIn("one", await async_get_tariffs(self.hass, "key", ["one"]))

    async def test_failed_requests_are_throttled_without_serving_stale_data(self):
        await async_get_tariffs(self.hass, "key", ["one"])
        cache = next(iter(self.hass.data.values()))
        cache.states["one"].last_request -= 3601
        self.session.post.return_value = Response(None, status=401)
        with self.assertRaises(APIError):
            await async_get_tariffs(self.hass, "key", ["one"])
        with self.assertRaises(RequestThrottled):
            await async_get_tariffs(self.hass, "key", ["one"])
        self.assertEqual(self.session.post.call_count, 2)


class MeteringPointValidationTests(unittest.IsolatedAsyncioTestCase):
    async def test_all_range_endpoints_are_inclusive_and_last_digit_is_ignored(self):
        ranges = (
            ("70705750007619000", "70705750008018999"),
            ("70705750004571000", "70705750004609999"),
            ("70705750002270000", "70705750002349999"),
            ("70705750001221000", "70705750001260999"),
            ("70705750008191000", "70705750008215999"),
            ("70705750008220000", "70705750008244999"),
        )
        hass = SimpleNamespace()
        for start, end in ranges:
            for prefix in (start, end):
                for last_digit in ("0", "9"):
                    point_id = prefix + last_digit
                    with self.subTest(point_id=point_id), patch(
                        "custom_components.glitrenett.config_flow.async_get_tariffs",
                        new=AsyncMock(return_value={point_id: {}}),
                    ) as fetch:
                        self.assertIsNone(await _validate_point(hass, "key", point_id))
                        fetch.assert_awaited_once_with(hass, "key", [point_id])
            for prefix in (str(int(start) - 1), str(int(end) + 1)):
                with self.subTest(prefix=prefix), patch(
                    "custom_components.glitrenett.config_flow.async_get_tariffs",
                    new=AsyncMock(),
                ) as fetch:
                    self.assertEqual(
                        await _validate_point(hass, "key", prefix + "0"),
                        "metering_point_out_of_range",
                    )
                    fetch.assert_not_awaited()

    async def test_invalid_input_in_both_flows_never_calls_api(self):
        cases = (
            ("70705750007619000", "invalid_metering_point_format"),
            ("7070575000761900000", "invalid_metering_point_format"),
            ("70705750007619000x", "invalid_metering_point_format"),
            ("７０７０５７５０００７６１９００００", "invalid_metering_point_format"),
            ("70705750007619 000", "invalid_metering_point_format"),
            ("707057500080190000", "metering_point_out_of_range"),
        )
        entry = SimpleNamespace(data={CONF_API_KEY: "key"})
        hass = SimpleNamespace(
            config_entries=SimpleNamespace(
                async_entries=lambda _: [],
                async_get_known_entry=lambda _: entry,
            )
        )
        for flow_type in (GlitrenettConfigFlow, GlitrenettMeteringPointFlow):
            for point_id, expected in cases:
                with self.subTest(flow=flow_type.__name__, point_id=point_id):
                    flow = flow_type()
                    flow.hass = hass
                    flow.context = {"source": "user"}
                    if isinstance(flow, GlitrenettConfigFlow):
                        await flow.async_step_user({CONF_API_KEY: "key"})
                        step = flow.async_step_metering_point
                    else:
                        flow.handler = ("entry", "metering_point")
                        step = flow.async_step_user
                    with patch(
                        "custom_components.glitrenett.config_flow.async_get_tariffs",
                        new=AsyncMock(),
                    ) as fetch:
                        result = await step(
                            {"name": "House", "metering_point_id": point_id}
                        )
                    self.assertEqual(
                        result["errors"], {"metering_point_id": expected}
                    )
                    fetch.assert_not_awaited()


class FlowTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.entries = []
        self.hass = SimpleNamespace(
            config_entries=SimpleNamespace(async_entries=lambda _: self.entries)
        )

    async def test_localized_setup_labels_and_help_links(self):
        integration_path = (
            Path(__file__).resolve().parents[1] / "custom_components" / "glitrenett"
        )
        manifest = json.loads((integration_path / "manifest.json").read_text())
        with TemporaryDirectory() as config_dir:
            hass = HomeAssistant(config_dir)
            async_setup(hass)
            integration = Integration(
                hass,
                "custom_components.glitrenett",
                integration_path,
                manifest,
                {path.name for path in integration_path.iterdir()},
            )
            try:
                with patch(
                    "homeassistant.helpers.translation.async_get_integrations",
                    new=AsyncMock(return_value={"glitrenett": integration}),
                ):
                    for language in ("en", "nb"):
                        translations = await async_get_translations(
                            hass, language, "config", {"glitrenett"}
                        )
                        flow = GlitrenettConfigFlow()
                        flow.hass = hass
                        flow.context = {"source": "user"}
                        for user_input in (None, {CONF_API_KEY: " "}):
                            with self.subTest(language=language, user_input=user_input):
                                result = await flow.async_step_user(user_input)
                                description = translations[
                                    "component.glitrenett.config.step.user.description"
                                ].format(**result["description_placeholders"])
                                self.assertRegex(
                                    description,
                                    r"\[[^\]]+\]\(https://www\.glitrenett\.no/"
                                    r"kunde/nettleie-og-priser/api-for-nettleiepriser\)",
                                )
                        result = await flow.async_step_user({CONF_API_KEY: "key"})
                        prefix = (
                            "component.glitrenett.config.step."
                            f"{result['step_id']}"
                        )
                        for field in result["data_schema"].schema:
                            with self.subTest(language=language, field=field.schema):
                                label = translations[f"{prefix}.data.{field.schema}"]
                                self.assertTrue(label)
                                self.assertNotEqual(label, field.schema)
                        subentry_translations = await async_get_translations(
                            hass, language, "config_subentries", {"glitrenett"}
                        )
                        for resources, step_prefix in (
                            (translations, prefix),
                            (
                                subentry_translations,
                                "component.glitrenett.config_subentries."
                                "metering_point.step.user",
                            ),
                        ):
                            with self.subTest(language=language, step=step_prefix):
                                self.assertRegex(
                                    resources[
                                        f"{step_prefix}.data_description."
                                        "metering_point_id"
                                    ],
                                    r"\[[^\]]+\]\(https://minside\.glitrenett\.no\)",
                                )
            finally:
                await hass.async_stop()

    async def test_initial_setup_multiple_points_and_duplicate(self):
        flow = GlitrenettConfigFlow()
        flow.hass = self.hass
        flow.context = {"source": "user"}
        step = await flow.async_step_user({CONF_API_KEY: " key "})
        self.assertEqual(step["step_id"], "metering_point")
        with patch(
            "custom_components.glitrenett.config_flow._validate_point",
            new=AsyncMock(return_value=None),
        ):
            step = await flow.async_step_metering_point(
                {"name": "House", "metering_point_id": "one", "add_another": True}
            )
            self.assertEqual(step["type"], FlowResultType.FORM)
            step = await flow.async_step_metering_point(
                {"name": "Again", "metering_point_id": "one", "add_another": False}
            )
            self.assertEqual(step["errors"]["base"], "already_configured")
            result = await flow.async_step_metering_point(
                {"name": "Cabin", "metering_point_id": "two", "add_another": False}
            )
        self.assertEqual(result["data"], {CONF_API_KEY: "key"})
        self.assertEqual([p["unique_id"] for p in result["subentries"]], ["one", "two"])

    async def test_subentry_uses_parent_key_and_rejects_duplicate(self):
        existing = SimpleNamespace(unique_id="one")
        entry = SimpleNamespace(
            data={CONF_API_KEY: "key"},
            get_subentries_of_type=lambda _: [existing],
        )
        self.entries.append(entry)
        self.hass.config_entries.async_get_known_entry = lambda _: entry
        flow = GlitrenettMeteringPointFlow()
        flow.hass = self.hass
        flow.handler = ("entry", "metering_point")
        flow.context = {"source": "user"}
        result = await flow.async_step_user(
            {"name": "House", "metering_point_id": "one"}
        )
        self.assertEqual(result["errors"]["base"], "already_configured")
        with patch(
            "custom_components.glitrenett.config_flow._validate_point",
            new=AsyncMock(return_value=None),
        ) as validate:
            result = await flow.async_step_user(
                {"name": "Cabin", "metering_point_id": "two"}
            )
        validate.assert_awaited_once_with(self.hass, "key", "two")
        self.assertEqual(result["unique_id"], "two")
        self.assertEqual(result["data"], {"metering_point_id": "two"})

    async def test_missing_point_is_an_explicit_error(self):
        flow = GlitrenettConfigFlow()
        flow.hass = self.hass
        flow.context = {"source": "user"}
        await flow.async_step_user({CONF_API_KEY: "key"})
        with patch(
            "custom_components.glitrenett.config_flow.async_get_tariffs",
            new=AsyncMock(return_value={}),
        ):
            result = await flow.async_step_metering_point(
                {"name": "Missing", "metering_point_id": "707057500076190000"}
            )
        self.assertEqual(result["errors"]["base"], "point_not_found")

    async def test_sensors_follow_subentry_list_and_are_grouped(self):
        points = [
            SimpleNamespace(
                subentry_id=point_id,
                data={"metering_point_id": point_id},
                title=point_id,
            )
            for point_id in ("one", "two")
        ]
        entry = SimpleNamespace(
            entry_id="account", get_subentries_of_type=lambda _: points
        )
        coordinator = MagicMock()
        hass = SimpleNamespace(data={"glitrenett": {"account": coordinator}})
        add_entities = MagicMock()
        await async_setup_entry(hass, entry, add_entities)
        self.assertEqual(add_entities.call_count, 2)
        for call, point_id in zip(add_entities.call_args_list, ("one", "two")):
            self.assertEqual(call.kwargs["config_subentry_id"], point_id)
            self.assertEqual(len(call.args[0]), 4)
        points.pop()
        add_entities.reset_mock()
        await async_setup_entry(hass, entry, add_entities)
        self.assertEqual(add_entities.call_count, 1)
        self.assertEqual(add_entities.call_args.kwargs["config_subentry_id"], "one")

    async def test_entry_change_reloads_parent(self):
        reload_entry = AsyncMock()
        hass = SimpleNamespace(
            config_entries=SimpleNamespace(async_reload=reload_entry)
        )
        await _async_reload_entry(hass, SimpleNamespace(entry_id="account"))
        reload_entry.assert_awaited_once_with("account")

    async def test_invalid_key_is_reported(self):
        flow = GlitrenettConfigFlow()
        flow.hass = self.hass
        flow.context = {"source": "user"}
        await flow.async_step_user({CONF_API_KEY: "key"})
        with patch(
            "custom_components.glitrenett.config_flow.async_get_tariffs",
            new=AsyncMock(side_effect=APIError(401)),
        ):
            result = await flow.async_step_metering_point(
                {"name": "House", "metering_point_id": "707057500076190000"}
            )
        self.assertEqual(result["errors"]["base"], "invalid_auth")

    async def test_reauth_reloads_failed_setup_without_update_listener(self):
        entry = SimpleNamespace(
            entry_id="account",
            data={CONF_API_KEY: "old"},
            update_listeners=[],
            get_subentries_of_type=lambda _: [
                SimpleNamespace(data={"metering_point_id": "one"})
            ],
        )
        self.hass.config_entries.async_update_entry = MagicMock(return_value=True)
        self.hass.config_entries.async_schedule_reload = MagicMock()
        flow = GlitrenettConfigFlow()
        flow.hass = self.hass
        flow.context = {"source": "reauth"}
        flow._reauth_entry = entry
        with patch(
            "custom_components.glitrenett.config_flow._validate_point",
            new=AsyncMock(return_value=None),
        ):
            result = await flow.async_step_reauth_confirm({CONF_API_KEY: "new"})
        self.assertEqual(result["reason"], "reauth_successful")
        self.hass.config_entries.async_schedule_reload.assert_called_once_with("account")


if __name__ == "__main__":
    unittest.main()
