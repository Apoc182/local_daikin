"""Tests for the post-off drying state machine (mold-proof workaround)."""

import logging
import time
from unittest.mock import MagicMock, patch

import pytest
from homeassistant.components.climate.const import HVACMode

from custom_components.local_daikin.climate import LocalDaikin
from custom_components.local_daikin.const import (
    CONF_POST_OFF_DRYING,
    CONF_POST_OFF_DRYING_MINUTES,
    POST_OFF_DRYING_START_DELAY,
)

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


def _status_response(mode: HVACMode, is_off: str, *, source=None, timer="0000") -> dict:
    """Build a dgc_status response for a given mode, power state and source."""
    pc = {
        "pn": "dgc_status",
        "pch": [
            {
                "pn": "e_1002",
                "pch": [
                    {"pn": "e_A002", "pch": [{"pn": "p_01", "pv": is_off}]},
                    {"pn": "e_3001", "pch": [{"pn": "p_01", "pv": MODE_HEX[mode]}]},
                    {"pn": "e_3003", "pch": [{"pn": "p_3B", "pv": timer}]},
                ],
            }
        ],
    }
    if source is not None:
        pc["pch"].append(
            {
                "pn": "last_ope",
                "pch": [
                    {"pn": "type", "pv": source},
                    {"pn": "time", "pv": "2026-11-12T00:00:00Z"},
                    {"pn": "chg_flg", "pv": 0},
                ],
            }
        )
    return {"responses": [{"rsc": 2004, "fr": INDOOR, "pc": pc}]}


def _entity(option: bool = True, minutes: int | None = None) -> LocalDaikin:
    options = {CONF_POST_OFF_DRYING: option}
    if minutes is not None:
        options[CONF_POST_OFF_DRYING_MINUTES] = minutes
    return LocalDaikin(IP, options=options)


T0 = time.time()
D = POST_OFF_DRYING_START_DELAY


def _off_from(prev: HVACMode, **fields) -> LocalDaikin:
    """Entity that just went OFF after `prev`, armed on the first poll."""
    entity = _entity()
    entity._hvac_mode = HVACMode.OFF
    entity._pre_transition_mode = prev
    for key, value in fields.items():
        setattr(entity, key, value)
    return entity


def _armed(source=None, **fields) -> LocalDaikin:
    entity = _off_from(HVACMode.COOL, _last_ope_type=source, **fields)
    entity._process_post_off_drying(now=T0)
    assert entity._drying_phase == "waiting"
    return entity


def _drying(source=100, deadline=None) -> LocalDaikin:
    entity = _entity()
    entity._drying_phase = "drying"
    entity._drying_deadline = deadline if deadline is not None else T0 + 3600
    entity._hvac_mode = HVACMode.FAN_ONLY
    entity._last_ope_type = source
    return entity


def _rejected() -> MagicMock:
    post = MagicMock()
    post.return_value.json.return_value = {"responses": [{"rsc": 3002}]}
    return post


def test_option_off_never_arms():
    entity = _entity(option=False)
    entity._hvac_mode = HVACMode.OFF
    entity._pre_transition_mode = HVACMode.COOL
    with patch(POST_PATH, _accepted_post()) as post:
        entity._process_post_off_drying(now=T0)
    assert entity._drying_phase is None
    post.assert_not_called()


def test_cool_off_arms_waiting_without_sending():
    entity = _off_from(HVACMode.COOL)
    with patch(POST_PATH, _accepted_post()) as post:
        entity._process_post_off_drying(now=T0)
    assert entity._drying_phase == "waiting"
    assert entity._drying_step_after == T0 + D
    post.assert_not_called()


def test_dry_off_arms_waiting():
    entity = _off_from(HVACMode.DRY)
    entity._process_post_off_drying(now=T0)
    assert entity._drying_phase == "waiting"


@pytest.mark.parametrize("prev", [HVACMode.HEAT, HVACMode.FAN_ONLY])
def test_heat_or_fan_off_does_not_arm(prev):
    entity = _off_from(prev)
    entity._process_post_off_drying(now=T0)
    assert entity._drying_phase is None


def test_waiting_does_not_decide_before_delay():
    entity = _armed(source=100)
    with patch(POST_PATH, _accepted_post()) as post:
        entity._process_post_off_drying(now=T0 + 2)
    assert entity._drying_phase == "waiting"
    post.assert_not_called()


def test_remote_off_skipped_after_delay(caplog):
    entity = _armed(source=1)
    with caplog.at_level(logging.DEBUG), patch(POST_PATH, _accepted_post()) as post:
        entity._process_post_off_drying(now=T0 + D)
        entity._process_post_off_drying(now=T0 + D + 60)
    assert entity._drying_phase is None
    post.assert_not_called()
    assert sum("remote" in r.getMessage() for r in caplog.records) == 1


def test_local_off_starts_fan_only():
    entity = _armed(source=100)
    now = T0 + D
    with patch(POST_PATH, _accepted_post()) as post:
        entity._process_post_off_drying(now=now)
    post.assert_called_once()
    # fan-only mode + power on only; no fan speed write (p_28)
    assert _leaves(post.call_args.kwargs["json"]) == [("p_01", "0000"), ("p_01", "01")]
    assert entity._drying_phase == "drying"
    assert entity._drying_deadline == now + 60 * 60
    assert entity._hvac_mode == HVACMode.FAN_ONLY


def test_app_off_starts_fan_only():
    entity = _armed(source=200)
    with patch(POST_PATH, _accepted_post()):
        entity._process_post_off_drying(now=T0 + D)
    assert entity._drying_phase == "drying"


def test_missing_source_dries():
    entity = _armed(source=None)
    with patch(POST_PATH, _accepted_post()):
        entity._process_post_off_drying(now=T0 + D)
    assert entity._drying_phase == "drying"


@pytest.mark.parametrize("minutes", [1, 2])
def test_off_timer_dries_even_with_remote_source(minutes):
    entity = _armed(source=1, _last_on_timer_minutes=minutes)
    with patch(POST_PATH, _accepted_post()):
        entity._process_post_off_drying(now=T0 + D)
    assert entity._drying_phase == "drying"


def test_remote_off_with_distant_timer_skipped():
    entity = _armed(source=1, _last_on_timer_minutes=30)
    with patch(POST_PATH, _accepted_post()) as post:
        entity._process_post_off_drying(now=T0 + D)
    assert entity._drying_phase is None
    post.assert_not_called()


def test_stale_source_on_first_off_poll_does_not_decide():
    entity = _armed(source=1)  # last_ope still shows the previous remote op
    entity._last_ope_type = 100  # caught up with the HA off by the delay poll
    with patch(POST_PATH, _accepted_post()):
        entity._process_post_off_drying(now=T0 + D)
    assert entity._drying_phase == "drying"


def test_waiting_cancelled_when_unit_back_on():
    entity = _armed(source=100)
    entity._hvac_mode = HVACMode.COOL
    with patch(POST_PATH, _accepted_post()) as post:
        entity._process_post_off_drying(now=T0 + D)
    assert entity._drying_phase is None
    post.assert_not_called()


def test_duration_option_used():
    entity = _entity(minutes=5)
    entity._hvac_mode = HVACMode.OFF
    entity._drying_phase = "waiting"
    entity._last_ope_type = 100
    with patch(POST_PATH, _accepted_post()):
        entity._process_post_off_drying(now=T0)
    assert entity._drying_deadline == T0 + 300


def test_drying_powers_off_at_deadline():
    entity = _drying(deadline=T0)
    with patch(POST_PATH, _accepted_post()) as post:
        entity._process_post_off_drying(now=T0)
    assert _leaves(post.call_args.kwargs["json"]) == [("p_01", "00")]
    assert entity._drying_phase is None
    assert entity._hvac_mode == HVACMode.OFF


def test_drying_waits_until_deadline():
    entity = _drying(deadline=T0 + 100)
    with patch(POST_PATH, _accepted_post()) as post:
        entity._process_post_off_drying(now=T0)
    assert entity._drying_phase == "drying"
    post.assert_not_called()


def test_drying_cancelled_on_mode_change(caplog):
    entity = _drying()
    entity._hvac_mode = HVACMode.COOL
    with caplog.at_level(logging.INFO):
        entity._process_post_off_drying(now=T0)
    assert entity._drying_phase is None
    assert "cancelled" in caplog.text


def test_drying_cancelled_when_switched_off():
    entity = _drying()
    entity._hvac_mode = HVACMode.OFF
    with patch(POST_PATH, _accepted_post()) as post:
        entity._process_post_off_drying(now=T0)
        assert entity._drying_phase is None
        entity._process_post_off_drying(now=T0 + 60)  # must not re-arm
    assert entity._drying_phase is None
    post.assert_not_called()


@pytest.mark.parametrize("source", [1, 200])
def test_remote_or_app_operation_during_drying_cancels(source):
    entity = _drying(source=source, deadline=T0)  # deadline passed: must not power off
    with patch(POST_PATH, _accepted_post()) as post:
        entity._process_post_off_drying(now=T0 + 1)
    assert entity._drying_phase is None
    post.assert_not_called()
    assert entity._hvac_mode == HVACMode.FAN_ONLY  # unit left running


@pytest.mark.parametrize(
    "call",
    [
        lambda e: e.set_fan_mode("Auto"),
        lambda e: e.set_swing_mode("off"),
        lambda e: e.set_temperature(24),
        lambda e: e.turn_on(),
    ],
)
def test_ha_service_call_during_drying_cancels(call):
    entity = _drying()
    with patch(POST_PATH, _accepted_post()):
        call(entity)
    assert entity._drying_phase is None


def test_rejected_start_retries_next_poll():
    entity = _armed(source=100)
    with patch(POST_PATH, _rejected()):
        entity._process_post_off_drying(now=T0 + D)
    assert entity._drying_phase == "waiting"
    with patch(POST_PATH, _accepted_post()):
        entity._process_post_off_drying(now=T0 + D + 60)
    assert entity._drying_phase == "drying"


def test_rejected_power_off_retries_next_poll():
    entity = _drying(deadline=T0)
    with patch(POST_PATH, _rejected()):
        entity._process_post_off_drying(now=T0)
    assert entity._drying_phase == "drying"
    with patch(POST_PATH, _accepted_post()):
        entity._process_post_off_drying(now=T0 + 60)
    assert entity._drying_phase is None


def test_parse_timer_minutes():
    assert LocalDaikin.parse_timer_minutes("4E00") == 78
    assert LocalDaikin.parse_timer_minutes("0100") == 1
    assert LocalDaikin.parse_timer_minutes("0000") == 0
    assert LocalDaikin.parse_timer_minutes(None) is None
    assert LocalDaikin.parse_timer_minutes("zz") is None


def test_full_cycle_through_update():
    """Wiring check: update() drives the state machine from real polls."""
    entity = _entity()
    with patch(POST_PATH) as post:
        post.return_value.json.return_value = _status_response(
            HVACMode.COOL, "01", source=1, timer="0000"
        )
        entity.update()
        assert entity.hvac_mode == HVACMode.COOL

        # HA turns it off; first OFF poll still reports the old source
        post.return_value.json.return_value = {"responses": [{"rsc": 2004}]}
        entity.turn_off()
        post.return_value.json.return_value = _status_response(
            HVACMode.COOL, "00", source=1
        )
        entity.update()
        assert entity._drying_phase == "waiting"

        # delay elapsed, last_ope has caught up: fan-only + power on
        post.return_value.json.return_value = _status_response(
            HVACMode.COOL, "00", source=100
        )
        entity._drying_step_after = time.time() - 1
        entity.update()
        assert entity._drying_phase == "drying"
        leaves = _leaves(post.call_args.kwargs["json"])
        assert leaves == [("p_01", "0000"), ("p_01", "01")]

        # deadline passes while fan-only is running: power off
        post.return_value.json.return_value = _status_response(
            HVACMode.FAN_ONLY, "01", source=100
        )
        entity._drying_deadline = time.time() - 1
        entity.update()
        assert entity._drying_phase is None
        assert _leaves(post.call_args.kwargs["json"]) == [("p_01", "00")]
        assert entity._hvac_mode == HVACMode.OFF


class FakeStore:
    def __init__(self, fail: bool = False, log: list | None = None):
        self.saved: list[float | None] = []
        self.fail = fail
        self.log = log

    def save(self, deadline):
        if self.fail:
            raise OSError("disk full")
        self.saved.append(deadline)
        if self.log is not None:
            self.log.append("save")


def _with_store(entity: LocalDaikin, store: FakeStore) -> LocalDaikin:
    entity._store = store
    return entity


def test_record_saved_before_fan_only_sent():
    order: list = []
    store = FakeStore(log=order)
    entity = _with_store(_armed(source=100), store)
    post = _accepted_post()
    post.side_effect = lambda *a, **k: (order.append("post"), post.return_value)[1]
    with patch(POST_PATH, post):
        entity._process_post_off_drying(now=T0 + D)
    assert store.saved == [T0 + D + entity._drying_seconds]
    assert order[0] == "save" and "post" in order


def test_store_failure_blocks_start_and_retries():
    store = FakeStore(fail=True)
    entity = _with_store(_armed(source=100), store)
    with patch(POST_PATH, _accepted_post()) as post:
        entity._process_post_off_drying(now=T0 + D)
    post.assert_not_called()
    assert entity._drying_phase == "waiting"
    store.fail = False
    with patch(POST_PATH, _accepted_post()):
        entity._process_post_off_drying(now=T0 + D + 60)
    assert entity._drying_phase == "drying"


def test_send_failure_clears_record():
    store = FakeStore()
    entity = _with_store(_armed(source=100), store)
    with patch(POST_PATH, _rejected()):
        entity._process_post_off_drying(now=T0 + D)
    assert store.saved == [T0 + D + entity._drying_seconds, None]
    assert entity._drying_phase == "waiting"


def test_finish_clears_record():
    store = FakeStore()
    entity = _with_store(_drying(deadline=T0), store)
    with patch(POST_PATH, _accepted_post()):
        entity._process_post_off_drying(now=T0)
    assert store.saved[-1] is None


def test_cancel_clears_record():
    store = FakeStore()
    entity = _with_store(_drying(), store)
    entity._hvac_mode = HVACMode.COOL
    entity._process_post_off_drying(now=T0)
    assert store.saved[-1] is None


def test_restore_none_leaves_idle():
    entity = _entity()
    entity.restore_drying(None)
    assert entity._drying_phase is None


def test_restore_resumes_and_powers_off_after_deadline():
    store = FakeStore()
    entity = _with_store(_entity(), store)
    entity.restore_drying(T0 - 1)
    entity._hvac_mode = HVACMode.FAN_ONLY
    entity._last_ope_type = 100
    with patch(POST_PATH, _accepted_post()) as post:
        entity._process_post_off_drying(now=T0)
    assert _leaves(post.call_args.kwargs["json"]) == [("p_01", "00")]
    assert store.saved[-1] is None


def test_restore_discards_when_unit_not_fan_only():
    store = FakeStore()
    entity = _with_store(_entity(), store)
    entity.restore_drying(T0 + 600)
    entity._hvac_mode = HVACMode.OFF
    with patch(POST_PATH, _accepted_post()) as post:
        entity._process_post_off_drying(now=T0)
    assert entity._drying_phase is None
    post.assert_not_called()
    assert store.saved[-1] is None


def test_restored_cycle_runs_even_if_option_disabled():
    entity = _entity(option=False)
    entity.restore_drying(T0 - 1)
    entity._hvac_mode = HVACMode.FAN_ONLY
    entity._last_ope_type = 100
    with patch(POST_PATH, _accepted_post()) as post:
        entity._process_post_off_drying(now=T0)
    assert _leaves(post.call_args.kwargs["json"]) == [("p_01", "00")]


def test_missing_source_during_drying_keeps_counting():
    entity = _drying(source=None)
    with patch(POST_PATH, _accepted_post()):
        entity._process_post_off_drying(now=T0)
    assert entity._drying_phase == "drying"


def test_deadline_passed_while_unreachable_powers_off_on_next_poll():
    entity = _drying(deadline=T0 + 100)
    # polls were skipped during the outage; the next one arrives after the deadline
    with patch(POST_PATH, _accepted_post()) as post:
        entity._process_post_off_drying(now=T0 + 5000)
    assert _leaves(post.call_args.kwargs["json"]) == [("p_01", "00")]


def test_ha_off_during_drying_clears_record_and_does_not_rearm():
    store = FakeStore()
    entity = _with_store(_drying(), store)
    with patch(POST_PATH, _accepted_post()):
        entity.turn_off()
        assert store.saved[-1] is None
        entity._process_post_off_drying(now=T0 + 60)
    assert entity._drying_phase is None


def test_unrecorded_fan_only_untouched():
    entity = _entity()
    entity._hvac_mode = HVACMode.FAN_ONLY
    entity._last_ope_type = 100
    with patch(POST_PATH, _accepted_post()) as post:
        for i in range(3):
            entity._process_post_off_drying(now=T0 + i * 3600)
    post.assert_not_called()
    assert entity._drying_phase is None


def test_post_off_drying_end_property():
    entity = _drying(deadline=T0 + 100)
    end = entity.post_off_drying_end
    assert end.tzinfo is not None and end.timestamp() == T0 + 100
    assert _entity().post_off_drying_end is None
