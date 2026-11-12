"""Per-unit feature capabilities, decided from the leaf metadata a poll returns.

The fixture is a real poll of a Daikin "Yokozuna V" (adp_i 3_12_3) that was
off: Comfort (p_1D) and Powerful (p_44) are read-only (pt=3), Econo and
Outdoor Quiet are absent, and the vertical louvers (pt=2) allow 0x17
(comfort) except in fan-only mode.
"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from homeassistant.components.climate.const import HVACMode
from homeassistant.exceptions import HomeAssistantError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.local_daikin import binary_sensor as binary_sensor_module
from custom_components.local_daikin import switch as switch_module
from custom_components.local_daikin.binary_sensor import DaikinFeatureBinarySensor
from custom_components.local_daikin.climate import LocalDaikin, louver_allows
from custom_components.local_daikin.switch import (
    DaikinComfortSwitch,
    DaikinPowerSwitch,
    DaikinQuietFanSwitch,
)

IP = "192.168.31.71"
INDOOR = "/dsiot/edge/adr_0100.dgc_status"
POST_PATH = "custom_components.local_daikin.climate.requests.post"
FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "yokozuna_v_poll.json").read_text()
)
ACCEPTED = {"responses": [{"rsc": 2004}]}


def _polled(fixture=FIXTURE) -> LocalDaikin:
    entity = LocalDaikin(IP)
    with patch(POST_PATH) as post:
        post.return_value.json.return_value = fixture
        entity.update()
    return entity


def _accepted_post():
    post = MagicMock()
    post.return_value.json.return_value = ACCEPTED
    return post


def _writes(post) -> list[list[tuple]]:
    """(to, path, pn, pv) of every leaf, one list per request sent."""

    def walk(to, nodes, path):
        for node in nodes:
            if "pv" in node:
                yield (to, path, node["pn"], node["pv"])
            else:
                yield from walk(to, node.get("pch", []), (*path, node["pn"]))

    return [
        [
            leaf
            for request in c.kwargs["json"]["requests"]
            for leaf in walk(request["to"], request["pc"]["pch"], ())
        ]
        for c in post.call_args_list
    ]


def test_capabilities_detected_from_leaf_metadata():
    entity = _polled()
    assert entity._feature_access == {
        "comfort": "louver",
        "econo": None,
        "outdoor_quiet": None,
        "powerful": "read",
    }
    assert entity._comfort_louver_modes == {
        HVACMode.AUTO, HVACMode.COOL, HVACMode.HEAT, HVACMode.DRY
    }
    assert entity._features["comfort"] == "off"
    assert entity._features["powerful"] == "off"


def test_comfort_on_writes_only_the_current_mode_vertical_louver():
    """Regression: on the real unit, Comfort also sent a Powerful clear to
    adr_0200 that was rejected and failed the whole command."""
    entity = _polled()
    entity._hvac_mode = HVACMode.COOL
    with patch(POST_PATH, _accepted_post()) as post:
        entity.set_feature("comfort", True)
    assert _writes(post) == [[(INDOOR, ("e_1002", "e_3001"), "p_05", "17000000")]]
    assert entity._features["comfort"] == "on"


def test_comfort_off_sets_the_vertical_louver_fixed():
    entity = _polled()
    entity._hvac_mode = HVACMode.HEAT
    with patch(POST_PATH, _accepted_post()) as post:
        entity.set_feature("comfort", False)
    assert _writes(post) == [[(INDOOR, ("e_1002", "e_3001"), "p_07", "00000000")]]
    assert entity._features["comfort"] == "off"


@pytest.mark.parametrize("mode", [HVACMode.FAN_ONLY, HVACMode.OFF])
def test_comfort_refused_where_the_louver_has_no_comfort_position(mode):
    entity = _polled()
    entity._hvac_mode = mode
    with (
        patch(POST_PATH, _accepted_post()) as post,
        pytest.raises(HomeAssistantError),
    ):
        entity.set_feature("comfort", True)
    post.assert_not_called()


@pytest.mark.parametrize("feature", ["powerful", "econo", "outdoor_quiet"])
def test_read_only_or_absent_features_are_never_written(feature):
    entity = _polled()
    entity._hvac_mode = HVACMode.COOL
    with (
        patch(POST_PATH, _accepted_post()) as post,
        pytest.raises(HomeAssistantError),
    ):
        entity.set_feature(feature, True)
    post.assert_not_called()


def test_unpolled_unit_refuses_feature_writes():
    with (
        patch(POST_PATH, _accepted_post()) as post,
        pytest.raises(HomeAssistantError),
    ):
        LocalDaikin(IP).set_feature("comfort", True)
    post.assert_not_called()


@pytest.mark.parametrize(
    ("mx", "allowed"),
    [("01808000", True), ("01800000", False), (None, False), ("zz", False)],
)
def test_louver_allows_reads_the_mx_bitmask(mx, allowed):
    assert louver_allows({"md": {"mx": mx}}, 0x17) is allowed


def _entry(hass, climate):
    entry = MockConfigEntry(domain="local_daikin", data={"ip_address": IP})
    entry.add_to_hass(hass)
    hass.data.setdefault("local_daikin", {})[entry.entry_id] = {
        "climate_entity": climate
    }
    return entry


async def _setup(hass, entry):
    switches, binary_sensors = [], []
    await switch_module.async_setup_entry(hass, entry, switches.extend)
    await binary_sensor_module.async_setup_entry(hass, entry, binary_sensors.extend)
    return switches, binary_sensors


async def test_entities_follow_the_unit_capabilities(hass):
    switches, binary_sensors = await _setup(hass, _entry(hass, _polled()))
    assert [type(e) for e in switches] == [
        DaikinPowerSwitch, DaikinQuietFanSwitch, DaikinComfortSwitch
    ]
    assert [e.feature for e in binary_sensors] == ["powerful"]
    binary_sensors[0].update()
    assert binary_sensors[0].is_on is False


async def test_entities_added_once_when_capabilities_arrive_after_setup(hass):
    """Unit unreachable at startup: feature entities appear after the first
    successful poll, and only once."""
    climate = LocalDaikin(IP)  # not polled yet: capabilities unknown
    switches, binary_sensors = await _setup(hass, _entry(hass, climate))
    assert [type(e) for e in switches] == [DaikinPowerSwitch, DaikinQuietFanSwitch]
    assert binary_sensors == []

    climate.hass = hass
    with patch(POST_PATH) as post:
        post.return_value.json.return_value = FIXTURE
        await hass.async_add_executor_job(climate.update)
        await hass.async_block_till_done()
        await hass.async_add_executor_job(climate.update)
        await hass.async_block_till_done()

    assert [type(e) for e in switches] == [
        DaikinPowerSwitch, DaikinQuietFanSwitch, DaikinComfortSwitch
    ]
    assert [type(e) for e in binary_sensors] == [DaikinFeatureBinarySensor]


def test_resource_without_payload_does_not_take_the_unit_offline():
    """A resource answered with an error code and no "pc" must only make its
    features unknown, not fail the poll (and skip post-off drying)."""
    import copy

    fixture = copy.deepcopy(FIXTURE)
    for response in fixture["responses"]:
        if response["fr"].startswith("/dsiot/edge/adr_0200"):
            response.pop("pc")
            response["rsc"] = 4000
    entity = _polled(fixture)
    assert entity.available
    assert entity._feature_access["powerful"] is None
    assert entity._feature_access["comfort"] == "louver"
