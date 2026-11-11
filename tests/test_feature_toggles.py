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


def test_set_feature_sends_even_when_cache_matches():
    """The cache can be up to a poll interval stale (e.g. Powerful timed out
    on the unit), so a matching cached state must not swallow the command."""
    entity = LocalDaikin(IP)
    entity._features["powerful"] = "on"
    with patch(POST_PATH, _accepted_post()) as post:
        entity.set_feature("powerful", True)
        leaves = _leaves(post.call_args.kwargs["json"])
    assert leaves == [("p_44", "01")]


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
    with patch(POST_PATH, _rejected_post()), pytest.raises(Exception, match="occured"):
        entity.set_feature("comfort", True)
    assert entity.extra_state_attributes["comfort"] is None


def test_rejected_write_keeps_exclusive_state():
    """A rejected write must not mark the opposite side as cleared."""
    import pytest

    entity = LocalDaikin(IP)
    entity._features["powerful"] = "on"
    with patch(POST_PATH, _rejected_post()), pytest.raises(Exception, match="occured"):
        entity.set_feature("econo", True)
    assert entity.extra_state_attributes["powerful"] == "on"
    assert entity.extra_state_attributes["econo"] is None


def test_missing_feature_nodes_do_not_log_warnings(caplog):
    """Models without these features must not log a WARNING every poll."""
    import logging

    response = {
        "responses": [
            {"rsc": 2004, "fr": INDOOR, "pc": {"pn": "dgc_status", "pch": []}}
        ]
    }
    with caplog.at_level(logging.WARNING):
        _entity_with_features(response)
    feature_pns = {pn for _, _, pn in FEATURE_MAP.values()}
    noisy = [
        r for r in caplog.records if any(pn in r.getMessage() for pn in feature_pns)
    ]
    assert noisy == []


async def test_turning_on_feature_refreshes_exclusive_switches():
    """Enabling Econo clears Powerful on the unit; the Powerful switch must
    refresh right away instead of showing On until the next poll."""
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    from custom_components.local_daikin import switch as switch_module

    climate = LocalDaikin(IP)
    climate._features["powerful"] = "on"
    hass = _fake_hass(climate)
    entry = SimpleNamespace(entry_id="entry-1", data={"ip_address": IP})
    added = []
    await switch_module.async_setup_entry(hass, entry, added.extend)
    by_type = {type(e): e for e in added}
    for entity in added:
        entity.hass = hass
        entity.schedule_update_ha_state = MagicMock()

    with patch(POST_PATH, _accepted_post()):
        by_type[DaikinEconoSwitch].turn_on()

    by_type[DaikinPowerfulSwitch].schedule_update_ha_state.assert_called_once_with(
        force_refresh=True
    )


def test_partially_rejected_write_keeps_cached_state():
    """Econo (indoor) + clearing Powerful (outdoor) spans two resources and
    gets two responses; a rejection in the second one must still count."""
    from unittest.mock import MagicMock

    import pytest

    entity = LocalDaikin(IP)
    entity._features["powerful"] = "on"
    post = MagicMock()
    post.return_value.json.return_value = {
        "responses": [{"rsc": 2004}, {"rsc": 4000}]
    }
    with patch(POST_PATH, post), pytest.raises(Exception, match="occured"):
        entity.set_feature("econo", True)
    assert entity.extra_state_attributes["powerful"] == "on"
    assert entity.extra_state_attributes["econo"] is None


def test_poll_without_feature_node_resets_cache_to_unknown():
    """A cached "on" must not stick once the unit stops reporting the node."""
    entity = _entity_with_features(_feature_response("comfort", "01"))
    assert entity.extra_state_attributes["comfort"] == "on"
    response = {
        "responses": [
            {"rsc": 2004, "fr": INDOOR, "pc": {"pn": "dgc_status", "pch": []}}
        ]
    }
    with patch(POST_PATH) as post:
        post.return_value.json.return_value = response
        entity.update()
    assert entity.extra_state_attributes["comfort"] is None


def test_poll_with_unexpected_feature_value_resets_cache_to_unknown():
    entity = _entity_with_features(_feature_response("econo", "01"))
    with patch(POST_PATH) as post:
        post.return_value.json.return_value = _feature_response("econo", "02")
        entity.update()
    assert entity.extra_state_attributes["econo"] is None


def test_empty_responses_count_as_rejected():
    """An empty response list must not be mistaken for an accepted write."""
    from unittest.mock import MagicMock

    import pytest

    entity = LocalDaikin(IP)
    post = MagicMock()
    post.return_value.json.return_value = {"responses": []}
    with patch(POST_PATH, post), pytest.raises(Exception, match="occured"):
        entity.set_feature("comfort", True)
    assert entity.extra_state_attributes["comfort"] is None
