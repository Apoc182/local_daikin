"""Tests for device feature toggles (comfort, econo, outdoor quiet, powerful)."""

from unittest.mock import patch

from custom_components.local_daikin.climate import FEATURE_MAP, LocalDaikin
from custom_components.local_daikin.switch import (
    DaikinComfortSwitch,
    DaikinEconoSwitch,
    DaikinOutdoorQuietSwitch,
    DaikinPowerfulSwitch,
)

IP = "192.168.31.71"
INDOOR = "/dsiot/edge/adr_0100.dgc_status"
OUTDOOR = "/dsiot/edge/adr_0200.dgc_status"

POST_PATH = "custom_components.local_daikin.climate.requests.post"


def _feature_response(feature: str, value: str) -> dict:
    """Build a multireq response exposing a single feature node."""
    to, path, pn = FEATURE_MAP[feature]
    return {
        "responses": [
            {
                "rsc": 2004,
                "fr": to,
                "pc": {
                    "pn": "dgc_status",
                    "pch": [
                        {
                            "pn": path[0],
                            "pch": [{"pn": path[1], "pch": [{"pn": pn, "pv": value}]}],
                        }
                    ],
                },
            }
        ]
    }


def _leaves(payload: dict) -> list[tuple[str, str]]:
    """Return (pn, pv) for every attribute leaf in a serialized request."""
    leaves: list[tuple[str, str]] = []

    def walk(nodes: list) -> None:
        for node in nodes:
            if "pv" in node:
                leaves.append((node["pn"], node["pv"]))
            walk(node.get("pch", []))

    for request in payload["requests"]:
        walk(request["pc"]["pch"])
    return leaves


ACCEPTED_RESPONSE = {"responses": [{"rsc": 2004}]}


def _entity_with_features(response: dict):
    entity = LocalDaikin(IP)
    with patch(POST_PATH) as post:
        post.return_value.json.return_value = response
        entity.update()
    return entity


def _accepted_post() -> dict:
    """A requests.post mock whose response carries a successful rsc."""
    from unittest.mock import MagicMock

    post = MagicMock()
    post.return_value.json.return_value = ACCEPTED_RESPONSE
    return post


def test_feature_parses_on():
    entity = _entity_with_features(_feature_response("comfort", "01"))
    assert entity.extra_state_attributes["comfort"] == "on"


def test_feature_parses_off():
    entity = _entity_with_features(_feature_response("econo", "00"))
    assert entity.extra_state_attributes["econo"] == "off"


def test_feature_missing_node_is_none():
    """Models that do not expose a feature must read back as unknown, not crash."""
    response = {
        "responses": [
            {"rsc": 2004, "fr": INDOOR, "pc": {"pn": "dgc_status", "pch": []}}
        ]
    }
    entity = _entity_with_features(response)
    assert entity.extra_state_attributes["comfort"] is None
    assert entity.extra_state_attributes["powerful"] is None


def test_outdoor_feature_reads_from_outdoor_resource():
    entity = _entity_with_features(_feature_response("outdoor_quiet", "01"))
    assert entity.extra_state_attributes["outdoor_quiet"] == "on"


def test_set_feature_sends_correct_attribute():
    entity = LocalDaikin(IP)
    with patch(POST_PATH, _accepted_post()) as post:
        entity.set_feature("comfort", True)
        payload = post.call_args.kwargs["json"]
    assert len(payload["requests"]) == 1
    request = payload["requests"][0]
    assert request["to"] == INDOOR
    node = request["pc"]["pch"][0]
    assert node["pn"] == "e_1002"
    node = node["pch"][0]
    assert node["pn"] == "e_3003"
    assert node["pch"][0] == {"pn": "p_1D", "pv": "01"}


def test_set_feature_off_sends_zero():
    entity = LocalDaikin(IP)
    with patch(POST_PATH, _accepted_post()) as post:
        entity.set_feature("econo", False)
        leaves = _leaves(post.call_args.kwargs["json"])
    assert leaves == [("p_24", "00")]


def test_enabling_comfort_disables_active_powerful():
    entity = LocalDaikin(IP)
    entity._features["powerful"] = "on"
    with patch(POST_PATH, _accepted_post()) as post:
        entity.set_feature("comfort", True)
        leaves = _leaves(post.call_args.kwargs["json"])
    assert leaves == [("p_1D", "01"), ("p_44", "00")]
    assert entity.extra_state_attributes["comfort"] == "on"
    assert entity.extra_state_attributes["powerful"] == "off"


def test_enabling_powerful_disables_active_trio():
    entity = LocalDaikin(IP)
    entity._features["comfort"] = "on"
    entity._features["econo"] = "on"
    entity._features["outdoor_quiet"] = "off"
    with patch(POST_PATH, _accepted_post()) as post:
        entity.set_feature("powerful", True)
        leaves = _leaves(post.call_args.kwargs["json"])
    assert ("p_44", "01") in leaves
    assert ("p_1D", "00") in leaves
    assert ("p_24", "00") in leaves
    assert len(leaves) == 3  # outdoor_quiet was already off, no write


def test_no_exclusion_write_when_cached_state_unknown():
    entity = LocalDaikin(IP)
    # _features left empty (fresh entity, unit not polled yet)
    with patch(POST_PATH, _accepted_post()) as post:
        entity.set_feature("powerful", True)
        leaves = _leaves(post.call_args.kwargs["json"])
    assert leaves == [("p_44", "01")]


def test_set_feature_noop_when_already_in_that_state():
    entity = LocalDaikin(IP)
    entity._features["comfort"] = "on"
    with patch(POST_PATH, _accepted_post()) as post:
        entity.set_feature("comfort", True)
    post.assert_not_called()


class _FakeHass:
    def __init__(self, climate):
        self.data = {"local_daikin": {"entry-1": {"climate_entity": climate}}}

    def async_create_task(self, *args, **kwargs):
        return None

    def create_task(self, *args, **kwargs):
        return None


def _fake_hass(climate):
    return _FakeHass(climate)



def test_switch_tracks_feature_state():
    climate = LocalDaikin(IP)
    climate._features["comfort"] = "on"
    switch = DaikinComfortSwitch(_fake_hass(climate), "entry-1", IP)
    switch.update()
    assert switch.is_on is True


def test_switch_unknown_feature_is_none():
    """A feature the model does not expose shows as unknown, not a fake off."""
    climate = LocalDaikin(IP)
    climate._features["comfort"] = None
    switch = DaikinComfortSwitch(_fake_hass(climate), "entry-1", IP)
    switch.update()
    assert switch.is_on is None


def test_switch_turn_on_sends_command():
    climate = LocalDaikin(IP)
    switch = DaikinEconoSwitch(_fake_hass(climate), "entry-1", IP)
    switch.hass = _fake_hass(climate)
    with patch(POST_PATH, _accepted_post()) as post:
        switch.turn_on()
        leaves = _leaves(post.call_args.kwargs["json"])
    assert leaves == [("p_24", "01")]
    assert switch.is_on is True


def test_switch_turn_off_sends_command():
    climate = LocalDaikin(IP)
    switch = DaikinPowerfulSwitch(_fake_hass(climate), "entry-1", IP)
    switch.hass = _fake_hass(climate)
    with patch(POST_PATH, _accepted_post()) as post:
        switch.turn_off()
        leaves = _leaves(post.call_args.kwargs["json"])
    assert leaves == [("p_44", "00")]
    assert switch.is_on is False


def test_switch_available_follows_climate():
    climate = LocalDaikin(IP)
    climate._available = False
    switch = DaikinOutdoorQuietSwitch(_fake_hass(climate), "entry-1", IP)
    assert switch.available is False

REJECTED_RESPONSE = {"responses": [{"rsc": 4000}]}


def _rejected_post():
    from unittest.mock import MagicMock

    post = MagicMock()
    post.return_value.json.return_value = REJECTED_RESPONSE
    return post


def test_rejected_write_keeps_cached_state():
    """A rejected write must not leave a fake "on" in the cache."""
    import pytest

    entity = LocalDaikin(IP)
    with patch(POST_PATH, _rejected_post()), pytest.raises(Exception):
        entity.set_feature("comfort", True)
    assert entity.extra_state_attributes["comfort"] is None


def test_rejected_write_keeps_exclusive_state():
    """A rejected write must not mark the opposite side as cleared."""
    import pytest

    entity = LocalDaikin(IP)
    entity._features["powerful"] = "on"
    with patch(POST_PATH, _rejected_post()), pytest.raises(Exception):
        entity.set_feature("econo", True)
    assert entity.extra_state_attributes["powerful"] == "on"
    assert entity.extra_state_attributes["econo"] is None
