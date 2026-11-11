"""Tests for the post-off drying store and its entry-removal handling."""

from unittest.mock import MagicMock, patch

from homeassistant.components.climate.const import HVACMode
from pytest_homeassistant_custom_component.common import MockConfigEntry
from test_post_off_drying import IP, POST_PATH, _status_response

from custom_components.local_daikin import async_remove_entry
from custom_components.local_daikin.const import CONF_IP_ADDRESS, DOMAIN
from custom_components.local_daikin.drying_store import DryingStore

ENTRY_ID = "entry1"
KEY = f"{DOMAIN}.post_off_drying.{ENTRY_ID}"


def _entry(hass):
    entry = MockConfigEntry(
        domain=DOMAIN, entry_id=ENTRY_ID, data={CONF_IP_ADDRESS: IP}
    )
    entry.add_to_hass(hass)
    return entry


def _post(*responses):
    post = MagicMock()
    post.return_value.json.side_effect = list(responses)
    return post


def _leaves(call):
    out = []

    def walk(nodes):
        for n in nodes:
            if "pv" in n:
                out.append((n["pn"], n["pv"]))
            walk(n.get("pch", []))

    for r in call.kwargs["json"]["requests"]:
        walk(r["pc"]["pch"])
    return out


async def test_save_from_executor_then_load(hass):
    store = DryingStore(hass, ENTRY_ID)
    await hass.async_add_executor_job(store.save, 123.5)
    assert await store.async_load() == 123.5


async def test_save_none_removes(hass):
    store = DryingStore(hass, ENTRY_ID)
    await hass.async_add_executor_job(store.save, 123.5)
    await hass.async_add_executor_job(store.save, None)
    assert await store.async_load() is None


async def test_load_ignores_garbage(hass, hass_storage):
    hass_storage[KEY] = {"version": 1, "data": {"deadline": "x"}}
    assert await DryingStore(hass, ENTRY_ID).async_load() is None


async def test_remove_entry_powers_off_running_drying(hass, hass_storage):
    hass_storage[KEY] = {"version": 1, "data": {"deadline": 9e9}}
    post = _post(
        _status_response(HVACMode.FAN_ONLY, "01"),
        {"responses": [{"rsc": 2004}]},
    )
    with patch(POST_PATH, post):
        await async_remove_entry(hass, _entry(hass))
    assert post.call_count == 2
    assert _leaves(post.call_args_list[1]) == [("p_01", "00")]
    assert KEY not in hass_storage


async def test_remove_entry_without_record_sends_nothing(hass):
    with patch(POST_PATH) as post:
        await async_remove_entry(hass, _entry(hass))
    post.assert_not_called()


async def test_remove_entry_leaves_unit_alone_if_not_fan_only(hass, hass_storage):
    hass_storage[KEY] = {"version": 1, "data": {"deadline": 9e9}}
    post = _post(_status_response(HVACMode.COOL, "01"))
    with patch(POST_PATH, post):
        await async_remove_entry(hass, _entry(hass))
    assert post.call_count == 1
    assert KEY not in hass_storage
