"""Tests for the post-off drying state machine (mold-proof workaround)."""

import time
from unittest.mock import MagicMock, patch

from homeassistant.components.climate.const import HVACMode

from custom_components.local_daikin.climate import LocalDaikin
from custom_components.local_daikin.const import CONF_POST_OFF_DRYING

IP = "192.168.31.71"
POST_PATH = "custom_components.local_daikin.climate.requests.post"
INDOOR = "/dsiot/edge/adr_0100.dgc_status"

MODE_HEX = {
    HVACMode.COOL: "0200",
    HVACMode.HEAT: "0100",
    HVACMode.FAN_ONLY: "0000",
    HVACMode.DRY: "0500",
}


def _accepted_post() -> MagicMock:
    post = MagicMock()
    post.return_value.json.return_value = {"responses": [{"rsc": 2004}]}
    return post


def _leaves(payload: dict) -> list[tuple[str, str]]:
    leaves: list[tuple[str, str]] = []

    def walk(nodes: list) -> None:
        for node in nodes:
            if "pv" in node:
                leaves.append((node["pn"], node["pv"]))
            walk(node.get("pch", []))

    for request in payload["requests"]:
        walk(request["pc"]["pch"])
    return leaves


def _status_response(mode: HVACMode, is_off: str) -> dict:
    """Build a dgc_status response for a given mode and power state."""
    return {
        "responses": [
            {
                "rsc": 2004,
                "fr": INDOOR,
                "pc": {
                    "pn": "dgc_status",
                    "pch": [
                        {
                            "pn": "e_1002",
                            "pch": [
                                {"pn": "e_A002", "pch": [{"pn": "p_01", "pv": is_off}]},
                                {
                                    "pn": "e_3001",
                                    "pch": [{"pn": "p_01", "pv": MODE_HEX[mode]}],
                                },
                            ],
                        }
                    ],
                },
            }
        ]
    }


def _entity(option: bool = True) -> LocalDaikin:
    return LocalDaikin(IP, options={CONF_POST_OFF_DRYING: option})


def test_option_off_never_triggers():
    entity = _entity(option=False)
    entity._pre_transition_mode = HVACMode.COOL
    with patch(POST_PATH, _accepted_post()) as post:
        entity._process_post_off_drying(now=time.time())
    assert entity._drying_phase is None
    post.assert_not_called()


def test_cool_to_off_enters_waiting():
    entity = _entity()
    entity._pre_transition_mode = HVACMode.COOL
    with patch(POST_PATH, _accepted_post()) as post:
        entity._process_post_off_drying(now=time.time())
    assert entity._drying_phase == "waiting"
    post.assert_not_called()  # no command yet, next poll confirms it is still off


def test_dry_to_off_enters_waiting():
    entity = _entity()
    entity._pre_transition_mode = HVACMode.DRY
    entity._process_post_off_drying(now=time.time())
    assert entity._drying_phase == "waiting"


def test_heat_to_off_does_not_trigger():
    entity = _entity()
    entity._pre_transition_mode = HVACMode.HEAT
    entity._process_post_off_drying(now=time.time())
    assert entity._drying_phase is None


def test_fan_to_off_does_not_trigger():
    entity = _entity()
    entity._pre_transition_mode = HVACMode.FAN_ONLY
    entity._process_post_off_drying(now=time.time())
    assert entity._drying_phase is None


def test_waiting_confirms_off_and_starts_drying():
    entity = _entity()
    entity._drying_phase = "waiting"
    now = time.time()
    with patch(POST_PATH, _accepted_post()) as post:
        entity._process_post_off_drying(now=now)
    assert entity._drying_phase == "drying"
    assert entity._drying_deadline is not None and entity._drying_deadline > now
    payload = post.call_args.kwargs["json"]
    assert all(r["to"] == INDOOR for r in payload["requests"])
    leaves = _leaves(payload)
    # fan-only mode, power on, quiet fan speed — all in one request
    assert leaves == [("p_01", "0000"), ("p_01", "01"), ("p_28", "0B00")]
    assert entity._hvac_mode == HVACMode.FAN_ONLY


def test_waiting_cancelled_when_unit_restarts():
    entity = _entity()
    entity._drying_phase = "waiting"
    entity._hvac_mode = HVACMode.COOL  # user took over or unit auto-started
    with patch(POST_PATH, _accepted_post()) as post:
        entity._process_post_off_drying(now=time.time())
    assert entity._drying_phase is None
    post.assert_not_called()


def test_drying_waits_until_deadline():
    entity = _entity()
    entity._drying_phase = "drying"
    entity._drying_deadline = time.time() + 3600
    entity._hvac_mode = HVACMode.FAN_ONLY
    with patch(POST_PATH, _accepted_post()) as post:
        entity._process_post_off_drying(now=time.time())
    assert entity._drying_phase == "drying"
    post.assert_not_called()


def test_drying_powers_off_at_deadline():
    entity = _entity()
    entity._drying_phase = "drying"
    entity._drying_deadline = time.time() - 1
    entity._hvac_mode = HVACMode.FAN_ONLY
    with patch(POST_PATH, _accepted_post()) as post:
        entity._process_post_off_drying(now=time.time())
    assert entity._drying_phase is None
    leaves = _leaves(post.call_args.kwargs["json"])
    assert leaves == [("p_01", "00")]
    assert entity._pre_transition_mode == HVACMode.OFF  # no immediate re-trigger


def test_drying_cancelled_when_mode_changed():
    entity = _entity()
    entity._drying_phase = "drying"
    entity._hvac_mode = HVACMode.COOL
    with patch(POST_PATH, _accepted_post()) as post:
        entity._process_post_off_drying(now=time.time())
    assert entity._drying_phase is None
    post.assert_not_called()


def test_drying_cancelled_when_powered_off():
    entity = _entity()
    entity._drying_phase = "drying"
    entity._hvac_mode = HVACMode.OFF  # user switched it off mid-drying
    with patch(POST_PATH, _accepted_post()) as post:
        entity._process_post_off_drying(now=time.time())
    assert entity._drying_phase is None
    post.assert_not_called()


def test_full_cycle_through_update():
    """Wiring check: update() drives the state machine from real polls."""
    entity = _entity()
    with patch(POST_PATH) as post:
        # unit cooling
        post.return_value.json.return_value = _status_response(HVACMode.COOL, "01")
        entity.update()
        assert entity.hvac_mode == HVACMode.COOL

        # HA (or anything) turns it off — still visible as off next poll
        post.return_value.json.return_value = _status_response(HVACMode.COOL, "00")
        entity.update()
        assert entity._drying_phase == "waiting"

        # still off — drying starts
        entity.update()
        assert entity._drying_phase == "drying"
        leaves = _leaves(post.call_args.kwargs["json"])
        assert ("p_28", "0B00") in leaves

        # deadline passes while fan-only is running — power off
        entity._drying_deadline = time.time() - 1
        post.return_value.json.return_value = _status_response(HVACMode.FAN_ONLY, "01")
        entity.update()
        assert entity._drying_phase is None
        leaves = _leaves(post.call_args.kwargs["json"])
        assert leaves == [("p_01", "00")]