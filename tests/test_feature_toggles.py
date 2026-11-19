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


def _writable() -> LocalDaikin:
    """A unit whose four feature leaves are all writable (pt=2), like the
    BRP069C4x/Alira units pydaikin verified."""
    entity = LocalDaikin(IP)
    entity._feature_access = dict.fromkeys(FEATURE_MAP, "write")
    return entity


def _sent(post) -> list[list[tuple[str, str]]]:
    """Leaves of each request sent, one list per request."""
    return [_leaves(c.kwargs["json"]) for c in post.call_args_list]


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
    entity = _writable()
    with patch(POST_PATH, _accepted_post()) as post:
        entity.set_feature("comfort", True)
        payload = post.call_args_list[0].kwargs["json"]
    assert len(payload["requests"]) == 1
    request = payload["requests"][0]
    assert request["to"] == INDOOR
    node = request["pc"]["pch"][0]
    assert node["pn"] == "e_1002"
    node = node["pch"][0]
    assert node["pn"] == "e_3003"
    assert node["pch"][0] == {"pn": "p_1D", "pv": "01"}


def test_set_feature_off_sends_zero():
    entity = _writable()
    with patch(POST_PATH, _accepted_post()) as post:
        entity.set_feature("econo", False)
        leaves = _leaves(post.call_args.kwargs["json"])
    assert leaves == [("p_24", "00")]


def test_enabling_comfort_disables_active_powerful():
    """The clear is a request of its own, after the accepted primary write."""
    entity = _writable()
    entity._features["powerful"] = "on"
    with patch(POST_PATH, _accepted_post()) as post:
        entity.set_feature("comfort", True)
    assert _sent(post) == [[("p_1D", "01")], [("p_44", "00")]]
    assert entity.extra_state_attributes["comfort"] == "on"
    assert entity.extra_state_attributes["powerful"] == "off"


def test_enabling_powerful_disables_every_exposed_trio_member():
    """A cached "off" may be stale (e.g. turned on by the remote since the
    last poll), so every exposed member is cleared, not only cached "on"."""
    entity = _writable()
    entity._features["comfort"] = "on"
    entity._features["econo"] = "on"
    entity._features["outdoor_quiet"] = "off"
    with patch(POST_PATH, _accepted_post()) as post:
        entity.set_feature("powerful", True)
    assert _sent(post) == [
        [("p_44", "01")], [("p_1D", "00")], [("p_24", "00")], [("p_3D", "00")]
    ]
    assert entity.extra_state_attributes["outdoor_quiet"] == "off"


def test_no_exclusion_write_to_read_only_or_absent_leaves():
    """Read-only (pt=3) and absent leaves are never written."""
    entity = _writable()
    entity._feature_access.update(
        comfort="read", econo=None, outdoor_quiet="louver"
    )
    with patch(POST_PATH, _accepted_post()) as post:
        entity.set_feature("powerful", True)
    assert _sent(post) == [[("p_44", "01")]]


def test_set_feature_sends_even_when_cache_matches():
    """The cache can be up to a poll interval stale (e.g. Powerful timed out
    on the unit), so a matching cached state must not swallow the command."""
    entity = _writable()
    entity._features["powerful"] = "on"
    with patch(POST_PATH, _accepted_post()) as post:
        entity.set_feature("powerful", True)
    assert _sent(post)[0] == [("p_44", "01")]


class _FakeHass:
    def __init__(self, climate):
        self.data = {"local_daikin": {"entry-1": {"climate_entity": climate}}}

    def async_create_task(self, target, *args, **kwargs):
        target.close()  # never run: avoids "coroutine was never awaited"

    def create_task(self, target, *args, **kwargs):
        target.close()


def _fake_hass(climate):
    return _FakeHass(climate)


def _entry(hass, climate):
    """A config entry whose climate entity is registered, as after setup."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    entry = MockConfigEntry(domain="local_daikin", data={"ip_address": IP})
    entry.add_to_hass(hass)
    hass.data.setdefault("local_daikin", {})[entry.entry_id] = {
        "climate_entity": climate
    }
    return entry



def test_switch_tracks_feature_state():
    climate = _writable()
    climate._features["comfort"] = "on"
    switch = DaikinComfortSwitch(_fake_hass(climate), "entry-1", IP)
    switch.update()
    assert switch.is_on is True


def test_switch_unknown_feature_is_none():
    """A feature the model does not expose shows as unknown, not a fake off."""
    climate = _writable()
    climate._features["comfort"] = None
    switch = DaikinComfortSwitch(_fake_hass(climate), "entry-1", IP)
    switch.update()
    assert switch.is_on is None


def test_switch_turn_on_sends_command():
    climate = _writable()
    switch = DaikinEconoSwitch(_fake_hass(climate), "entry-1", IP)
    switch.hass = _fake_hass(climate)
    with patch(POST_PATH, _accepted_post()) as post:
        switch.turn_on()
    assert _sent(post)[0] == [("p_24", "01")]
    assert switch.is_on is True


def test_switch_turn_off_sends_command():
    climate = _writable()
    switch = DaikinPowerfulSwitch(_fake_hass(climate), "entry-1", IP)
    switch.hass = _fake_hass(climate)
    with patch(POST_PATH, _accepted_post()) as post:
        switch.turn_off()
        leaves = _leaves(post.call_args.kwargs["json"])
    assert leaves == [("p_44", "00")]
    assert switch.is_on is False


def test_switch_available_follows_climate():
    climate = _writable()
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

    entity = _writable()
    with patch(POST_PATH, _rejected_post()), pytest.raises(Exception, match="occured"):
        entity.set_feature("comfort", True)
    assert entity.extra_state_attributes["comfort"] is None


def test_rejected_write_keeps_exclusive_state():
    """A rejected write must not mark the opposite side as cleared."""
    import pytest

    entity = _writable()
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


async def test_turning_on_feature_refreshes_exclusive_switches(hass):
    """Enabling Econo clears Powerful on the unit; the Powerful switch must
    refresh right away instead of showing On until the next poll."""
    from unittest.mock import MagicMock

    from custom_components.local_daikin import switch as switch_module

    climate = _writable()
    climate._features["powerful"] = "on"
    entry = _entry(hass, climate)
    added = []
    await switch_module.async_setup_entry(hass, entry, added.extend)
    by_type = {type(e): e for e in added}
    for entity in added:
        entity.hass = hass
        entity.schedule_update_ha_state = MagicMock()

    with patch(POST_PATH, _accepted_post()):
        await hass.async_add_executor_job(by_type[DaikinEconoSwitch].turn_on)

    by_type[DaikinPowerfulSwitch].schedule_update_ha_state.assert_called_once_with(
        force_refresh=True
    )


def test_rejected_clear_does_not_fail_the_accepted_write():
    """On the real unit the Powerful clear was rejected (4000) while the
    Comfort write was accepted; the accepted write must still count."""
    from unittest.mock import MagicMock

    entity = _writable()
    entity._features["powerful"] = "on"
    post = MagicMock()
    post.return_value.json.side_effect = [ACCEPTED_RESPONSE, REJECTED_RESPONSE]
    with patch(POST_PATH, post):
        entity.set_feature("econo", True)
    assert entity.extra_state_attributes["econo"] == "on"
    assert entity.extra_state_attributes["powerful"] == "on"


def test_multi_response_rejection_still_counts():
    """_send_attribute: any rejected response fails the request."""
    from unittest.mock import MagicMock

    import pytest

    entity = _writable()
    post = MagicMock()
    post.return_value.json.return_value = {
        "responses": [{"rsc": 2004}, {"rsc": 4000}]
    }
    with patch(POST_PATH, post), pytest.raises(Exception, match="occured"):
        entity.set_feature("econo", True)
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

    entity = _writable()
    post = MagicMock()
    post.return_value.json.return_value = {"responses": []}
    with patch(POST_PATH, post), pytest.raises(Exception, match="occured"):
        entity.set_feature("comfort", True)
    assert entity.extra_state_attributes["comfort"] is None


def test_feature_switch_refreshes_climate_entity_state():
    """The climate entity exposes the features as attributes; they must
    update right after a write, not on the next climate poll."""
    from unittest.mock import MagicMock

    climate = _writable()
    climate.hass = _fake_hass(climate)  # added to HA, as in production
    climate.schedule_update_ha_state = MagicMock()
    switch = DaikinEconoSwitch(_fake_hass(climate), "entry-1", IP)
    switch.hass = _fake_hass(climate)
    switch.schedule_update_ha_state = MagicMock()
    with patch(POST_PATH, _accepted_post()):
        switch.turn_on()
        switch.turn_off()
    assert climate.schedule_update_ha_state.call_count == 2
