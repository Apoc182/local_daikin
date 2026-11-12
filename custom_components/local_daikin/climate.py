import logging
import requests
from requests.exceptions import RequestException
from homeassistant.components.climate import ClimateEntity, ClimateEntityFeature
from homeassistant.components.climate.const import (
    HVACMode,
    SWING_OFF,
    SWING_BOTH,
    SWING_VERTICAL,
    SWING_HORIZONTAL
)
from homeassistant.const import UnitOfTemperature
from homeassistant.helpers.device_registry import format_mac
from typing import Any, List
from dataclasses import dataclass, field
from enum import StrEnum
from time import time

from homeassistant.helpers.device_registry import DeviceInfo

from datetime import UTC, datetime, timedelta

from .drying_store import DryingStore
from .const import (
    CONF_POST_OFF_DRYING,
    CONF_POST_OFF_DRYING_MINUTES,
    LAST_OPE_LOCAL,
    LAST_OPE_REMOTE,
    OFF_TIMER_WINDOW_MINUTES,
    POST_OFF_DRYING_DEFAULT_MINUTES,
    POST_OFF_DRYING_START_DELAY,
)

SCAN_INTERVAL = timedelta(seconds=60)

# Timeout for all HTTP requests to the Daikin unit (seconds)
REQUEST_TIMEOUT = 10

# Retry settings for initial setup
SETUP_MAX_RETRIES = 3
SETUP_RETRY_DELAY = 5  # seconds

_LOGGER = logging.getLogger(__name__)


@dataclass
class DaikinAttribute:
    name: str
    value: float
    path: list[str]
    to: str

    def format(self) -> str:
        return {"pn": self.name, "pv": self.value}

class HAFanMode(StrEnum):
    FAN_QUIET = "Quiet"
    FAN_AUTO = "Auto"
    FAN_LEVEL1 = "Level 1"
    FAN_LEVEL2 = "Level 2"
    FAN_LEVEL3 = "Level 3"
    FAN_LEVEL4 = "Level 4"
    FAN_LEVEL5 = "Level 5"



TURN_OFF_SWING_AXIS = "000000"
TURN_ON_SWING_AXIS = "0F0000"



FAN_MODE_MAP = {
    HAFanMode.FAN_AUTO : "0A00",
    HAFanMode.FAN_QUIET : "0B00",
    HAFanMode.FAN_LEVEL1 : "0300",
    HAFanMode.FAN_LEVEL2 : "0400",
    HAFanMode.FAN_LEVEL3 : "0500",
    HAFanMode.FAN_LEVEL4 : "0600",
    HAFanMode.FAN_LEVEL5 : "0700"
}

# Vertical, horizontal
HVAC_MODE_TO_SWING_ATTR_NAMES = {
    HVACMode.AUTO : ("p_20", "p_21"),
    HVACMode.COOL : ("p_05", "p_06"),
    HVACMode.HEAT : ("p_07", "p_08"),
    HVACMode.FAN_ONLY : ("p_24", "p_25"),
    HVACMode.DRY : ("p_22", "p_23")
}

HVAC_MODE_TO_FAN_SPEED_ATTR_NAME = {
    HVACMode.AUTO : "p_26",
    HVACMode.COOL : "p_09",
    HVACMode.HEAT : "p_0A",
    HVACMode.FAN_ONLY : "p_28",
    # HVACMode.DRY : "dummy" There is no fan mode for dry. It's always automatic.
}


MODE_MAP = {
    "0300" : HVACMode.AUTO,
    "0200" : HVACMode.COOL,
    "0100" : HVACMode.HEAT,
    "0000" : HVACMode.FAN_ONLY,
    "0500" : HVACMode.DRY
}


HVAC_TO_TEMP_HEX = {
    HVACMode.COOL : "p_02",
    HVACMode.HEAT : "p_03",
    HVACMode.AUTO : "p_1D"
}



REVERSE_MODE_MAP = {v: k for k, v in MODE_MAP.items()}
REVERSE_FAN_MODE_MAP = {v: k for k, v in FAN_MODE_MAP.items()}

@dataclass
class DaikinRequest:
    attributes: list[DaikinAttribute] = field(default_factory=list)


    def serialize(self, payload=None) -> dict:
        if payload is None:
            payload = {
                'requests' : []
            }

        def get_existing_index(name: str, children: list[dict]) -> int:
            for index, child in enumerate(children):
                if child.get("pn") == name:
                    return index
            return -1
        
        def get_existing_to(to: str, requests: list[dict]) -> bool:
            for request in requests:
                this_to = request.get("to")
                if this_to == to:
                    return request
            return None

        for attribute in self.attributes:
            to = get_existing_to(attribute.to, payload['requests'])
            if to is None:
                payload['requests'].append({
                    'op': 3,
                    'pc' : {
                        "pn" : "dgc_status",
                        "pch" : []
                    },
                    "to": attribute.to
                })
                to = payload['requests'][-1]
            entry = to['pc']['pch']
            for pn in attribute.path:
                index = get_existing_index(pn, entry)
                if index == -1:
                    entry.append({"pn": pn, "pch": []})
                entry = entry[-1]['pch']
            entry.append(attribute.format())
        return payload

        



async def async_setup_entry(hass, entry, async_add_entities):
    ip = entry.data["ip_address"]
    store = DryingStore(hass, entry.entry_id)
    entity = LocalDaikin(ip, options=entry.options, store=store)
    entity.restore_drying(await store.async_load())

    # Retry initial update with backoff — Daikin units can be slow after HA reboot
    import asyncio
    for attempt in range(1, SETUP_MAX_RETRIES + 1):
        try:
            await hass.async_add_executor_job(entity.update)
            break
        except Exception as err:
            if attempt < SETUP_MAX_RETRIES:
                _LOGGER.warning(
                    "Daikin %s: setup attempt %d/%d failed (%s), retrying in %ds...",
                    ip, attempt, SETUP_MAX_RETRIES, err, SETUP_RETRY_DELAY * attempt
                )
                await asyncio.sleep(SETUP_RETRY_DELAY * attempt)
            else:
                _LOGGER.error(
                    "Daikin %s: setup failed after %d attempts (%s). "
                    "Entity will be added in unavailable state and retry on next poll.",
                    ip, SETUP_MAX_RETRIES, err
                )
                entity._available = False

    try:
        await entity.initialize_unique_id(hass)
    except Exception as err:
        _LOGGER.warning("Daikin %s: could not fetch MAC for unique_id (%s), using IP fallback", ip, err)

    # Register entity for use by switch.py / select.py / sensor.py
    hass.data["local_daikin"][entry.entry_id]["climate_entity"] = entity

    async_add_entities([entity])

class LocalDaikin(ClimateEntity):
    def __init__(
        self,
        ip_address: str,
        options: dict[str, Any] | None = None,
        store: Any | None = None,
    ):
        self._name = "Local Daikin"
        self.url = f"http://{ip_address}/dsiot/multireq"
        options = options or {}
        self._post_off_drying = bool(options.get(CONF_POST_OFF_DRYING, False))
        minutes = options.get(
            CONF_POST_OFF_DRYING_MINUTES, POST_OFF_DRYING_DEFAULT_MINUTES
        )
        self._drying_seconds = minutes * 60
        self._store = store  # None = no persistence
        # Post-off drying state machine (mold-proof workaround). Driven by the
        # 60s poll; no timers or extra HTTP calls. The unit's own MOLD PROOF
        # cycle does not run after a WiFi (local/app) off, but does after an IR
        # remote off, so the trigger is the operation source the unit reports.
        # None | "waiting" | "drying"
        self._drying_phase: str | None = None
        self._drying_deadline: float | None = None
        self._drying_step_after: float = 0.0  # earliest time for the next step
        self._drying_fan_pending: bool = False  # fan Auto still to be written
        self._drying_restored_unconfirmed: bool = False  # restored, not yet polled
        self._pre_transition_mode: HVACMode = HVACMode.OFF
        self._last_on_timer_minutes: int | None = None  # off timer while last on
        self._off_by_timer: bool = False
        self._last_ope_type: int | None = None
        self._off_timer_minutes: int | None = None
        self._hvac_mode = HVACMode.OFF
        self._fan_mode = HAFanMode.FAN_QUIET
        self._swing_mode = SWING_OFF
        self._temperature = None
        self._outside_temperature = None
        self._target_temperature = None
        self._current_temperature = None
        self._current_humidity = None
        self._runtime_today = None
        self._energy_today = None
        self._mac = None
        self._max_temp = 30 # may need some logic to set this based on the device ID
        self._min_temp = 10
        self._available = True

        self._ip = ip_address
        self._name = f"Local Daikin ({ip_address})"
        self._attr_unique_id = f"daikin_climate_{ip_address}"
            

        self._attr_hvac_modes = [HVACMode.OFF, HVACMode.HEAT, HVACMode.COOL, HVACMode.AUTO, HVACMode.DRY, HVACMode.FAN_ONLY]
        self._attr_fan_modes = [
            HAFanMode.FAN_QUIET, 
            HAFanMode.FAN_AUTO, 
            HAFanMode.FAN_LEVEL1, 
            HAFanMode.FAN_LEVEL2, 
            HAFanMode.FAN_LEVEL3, 
            HAFanMode.FAN_LEVEL4, 
            HAFanMode.FAN_LEVEL5
        ]
        self._attr_swing_modes = [
            SWING_OFF,
            SWING_BOTH,
            SWING_VERTICAL,
            SWING_HORIZONTAL
        ]
        self._attr_supported_features = ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.TURN_OFF | ClimateEntityFeature.TURN_ON | ClimateEntityFeature.FAN_MODE | ClimateEntityFeature.SWING_MODE
        self._enable_turn_on_off_backwards_compatibility = False
        
    @property
    def available(self) -> bool:
        """Return True if the entity is available."""
        return self._available

    def set_hvac_mode(self, hvac_mode):
        _LOGGER.info("Set Hvac mode to " + str(hvac_mode))

        if hvac_mode == HVACMode.OFF:
            self.turn_off()
        else:
            new_mode = REVERSE_MODE_MAP.get(hvac_mode)
            if new_mode is None:
                raise Exception(f"Unknown hvac mode {hvac_mode}")
            attribute = DaikinAttribute("p_01", new_mode, ["e_1002", "e_3001"], "/dsiot/edge/adr_0100.dgc_status")

            # Optimistic update
            self._hvac_mode = hvac_mode

            # Potentially add the turn on attribute here, unsure.
            self._update_state(True)
            self._send_attribute(DaikinRequest([attribute]).serialize())
            self._user_takeover()


    async def initialize_unique_id(self, hass):
        payload = {
            "requests": [
                {"op": 2, "to": "/dsiot/edge.adp_i"}
            ]
        }
        response = await hass.async_add_executor_job(
            lambda: requests.post(self.url, json=payload, timeout=REQUEST_TIMEOUT)
        )
        response.raise_for_status()
        data = response.json()
        self._mac = format_mac(self.find_value_by_pn(data, "/dsiot/edge.adp_i", "adp_i", "mac"))

    @property
    def device_info(self):
        return DeviceInfo(
            identifiers={("local_daikin", self._ip)},
            name="Local Daikin AC",
            manufacturer="Daikin",
            model="LAN Adapter",
            sw_version="1.0"
        )

    @property
    def name(self):
        """Return the name of the entity."""
        return self._name

    @property
    def hvac_mode(self):
        """Return current operation."""
        return self._hvac_mode.value

    @property
    def fan_mode(self):
        """Return current operation."""
        return self._fan_mode.value

    @property
    def swing_mode(self):
        return self._swing_mode

    @property
    def fan_modes(self):
        return [mode.value for mode in self._attr_fan_modes]

    @property
    def swing_modes(self):
        return self._attr_swing_modes

    @property
    def hvac_modes(self):
        return [mode.value for mode in self._attr_hvac_modes]

    @property
    def should_poll(self):
        return True

    def set_fan_mode(self, fan_mode: str):
        mode = FAN_MODE_MAP[fan_mode]
        name = HVAC_MODE_TO_FAN_SPEED_ATTR_NAME.get(self.hvac_mode)

        # If in dry mode for example, you cannot set the fan speed. So we ignore anything we cant find in this map.
        if name is not None:
            self._fan_mode = HAFanMode(fan_mode)  # optimistic
            mode_attr = DaikinAttribute(name, mode, ["e_1002", "e_3001"], "/dsiot/edge/adr_0100.dgc_status")
            self._send_attribute(DaikinRequest([mode_attr]).serialize())
            self._user_takeover()
        else:
            self._fan_mode = HAFanMode.FAN_AUTO

    def set_swing_mode(self, swing_mode: str):
        if self.hvac_mode == HVACMode.OFF:
            return
        self._swing_mode = swing_mode  # optimistic
        vertical_axis_command = TURN_OFF_SWING_AXIS if swing_mode in (SWING_OFF, SWING_HORIZONTAL) else TURN_ON_SWING_AXIS
        horizontal_axis_command = TURN_OFF_SWING_AXIS if swing_mode in (SWING_OFF, SWING_VERTICAL) else TURN_ON_SWING_AXIS
        vertical_attr_name, horizontal_attr_name = HVAC_MODE_TO_SWING_ATTR_NAMES[self.hvac_mode]
        self._send_attribute(
            DaikinRequest(
                [
                    DaikinAttribute(horizontal_attr_name, horizontal_axis_command, ["e_1002", "e_3001"], "/dsiot/edge/adr_0100.dgc_status"),
                    DaikinAttribute(vertical_attr_name, vertical_axis_command, ["e_1002", "e_3001"], "/dsiot/edge/adr_0100.dgc_status")
                ]
            ).serialize()
        )
        self._user_takeover()


    def _persist(self, deadline: float | None) -> bool:
        """Record the drying deadline (None clears it); False if the store failed."""
        if self._store is None:
            return True
        try:
            self._store.save(deadline)
        except Exception as err:
            _LOGGER.warning("Daikin %s: could not persist drying state (%s)", self._ip, err)
            return False
        return True

    def restore_drying(self, deadline: float | None) -> None:
        """Resume a cycle recorded before a restart; the next poll validates it."""
        if deadline is not None:
            self._drying_phase = "drying"
            self._drying_deadline = deadline
            self._drying_restored_unconfirmed = True
            self._drying_fan_pending = True
            self._drying_step_after = 0.0  # the unit has long settled

    @property
    def post_off_drying_end(self) -> datetime | None:
        # Read once: a cancel on the executor may clear it between two reads.
        deadline = self._drying_deadline
        if self._drying_phase != "drying" or deadline is None:
            return None
        return datetime.fromtimestamp(deadline, tz=UTC)

    def _cancel_drying(self, reason: str) -> None:
        _LOGGER.info("Daikin %s: post-off drying cancelled (%s)", self._ip, reason)
        self._drying_phase = None
        self._drying_deadline = None
        self._drying_restored_unconfirmed = False
        self._persist(None)

    def _user_takeover(self) -> None:
        """Hand the unit back after an accepted HA command while drying.

        "waiting" is left to polling: it sees the unit come back on.
        """
        if self._drying_phase == "drying":
            self._cancel_drying("changed from Home Assistant")

    def _process_post_off_drying(self, now: float) -> None:
        """Advance the post-off drying state machine on each poll.

        None    -> waiting  on a COOL/DRY -> OFF transition (option on)
        waiting -> None     unit on again, or the off came from the IR remote
                            (the unit runs its own MOLD PROOF cycle)
        waiting -> drying   after the start delay (last_ope has caught up):
                            fan-only + power on, at the unit's own fan speed;
                            or a failed start the unit applied (reads FAN_ONLY)
        drying  -> drying   fan Auto, sent on its own after the start delay
        drying  -> waiting  first poll after a restore finds the unit OFF and
                            not operated by remote/app: the start never landed
        drying  -> None     at the deadline (power off), or cancelled if the
                            mode changed or the remote/app operated the unit
        """
        hvac = self._hvac_mode

        if self._drying_phase is None:
            if (
                self._post_off_drying
                and hvac == HVACMode.OFF
                and self._pre_transition_mode in (HVACMode.COOL, HVACMode.DRY)
            ):
                self._drying_phase = "waiting"
                self._drying_step_after = now + POST_OFF_DRYING_START_DELAY
                self._off_by_timer = (
                    self._last_on_timer_minutes is not None
                    and 1 <= self._last_on_timer_minutes <= OFF_TIMER_WINDOW_MINUTES
                )
                _LOGGER.debug(
                    "Daikin %s: %s off seen — post-off drying armed",
                    self._ip, self._pre_transition_mode.value,
                )
            if hvac != HVACMode.OFF:
                self._last_on_timer_minutes = self._off_timer_minutes
            self._pre_transition_mode = hvac
            return

        if self._drying_phase == "waiting":
            if hvac != HVACMode.OFF:
                if self._drying_deadline is not None:
                    if hvac == HVACMode.FAN_ONLY:
                        # A start failed (e.g. timed out) but the unit applied it.
                        self._drying_phase = "drying"
                        self._drying_fan_pending = True
                        self._drying_step_after = now + POST_OFF_DRYING_START_DELAY
                        return
                    self._cancel_drying(f"mode is {hvac.value}")
                self._drying_phase = None
                self._pre_transition_mode = hvac
                self._last_on_timer_minutes = self._off_timer_minutes
                return
            if now < self._drying_step_after:
                return
            if self._last_ope_type == LAST_OPE_REMOTE and not self._off_by_timer:
                _LOGGER.debug(
                    "Daikin %s: remote off — built-in MOLD PROOF expected, "
                    "post-off drying skipped",
                    self._ip,
                )
                if self._drying_deadline is not None:
                    self._cancel_drying("remote off")
                self._drying_phase = None
                self._pre_transition_mode = HVACMode.OFF
                return
            deadline = now + self._drying_seconds
            # Save before sending: a crash after the send must not lose the record.
            if not self._persist(deadline):
                return
            try:
                self._send_attribute(
                    DaikinRequest(
                        [
                            DaikinAttribute(
                                "p_01",
                                REVERSE_MODE_MAP[HVACMode.FAN_ONLY],
                                ["e_1002", "e_3001"],
                                "/dsiot/edge/adr_0100.dgc_status",
                            ),
                            DaikinAttribute(
                                "p_01",
                                "01",
                                ["e_1002", "e_A002"],
                                "/dsiot/edge/adr_0100.dgc_status",
                            ),
                        ]
                    ).serialize()
                )
            except Exception as err:
                # Stay in "waiting": the next poll retries, or adopts the cycle if
                # the unit applied the command anyway (e.g. the reply timed out).
                _LOGGER.warning(
                    "Daikin %s: post-off drying start failed, retrying next poll (%s)",
                    self._ip, err,
                )
                self._drying_deadline = deadline
                return
            self._drying_deadline = deadline
            self._drying_phase = "drying"
            self._drying_fan_pending = True
            self._drying_step_after = now + POST_OFF_DRYING_START_DELAY
            self._hvac_mode = HVACMode.FAN_ONLY  # optimistic
            _LOGGER.info(
                "Daikin %s: post-off drying started (source %s), off in %d min",
                self._ip, self._last_ope_type, self._drying_seconds // 60,
            )
            return

        # drying
        restored = self._drying_restored_unconfirmed
        self._drying_restored_unconfirmed = False
        if (
            restored
            and hvac == HVACMode.OFF
            and now < self._drying_deadline
            and self._last_ope_type in (None, LAST_OPE_LOCAL)
        ):
            # Recorded before a restart, but the start never landed: retry it.
            _LOGGER.info(
                "Daikin %s: restored drying not running — retrying start", self._ip
            )
            self._drying_phase = "waiting"
            self._drying_step_after = now + POST_OFF_DRYING_START_DELAY
            return

        if hvac != HVACMode.FAN_ONLY:
            self._cancel_drying(f"mode is {hvac.value}")
            self._pre_transition_mode = hvac
            if hvac != HVACMode.OFF:
                self._last_on_timer_minutes = self._off_timer_minutes
            return

        if self._last_ope_type is not None and self._last_ope_type != LAST_OPE_LOCAL:
            self._cancel_drying("operated from remote or app")
            return

        if now >= self._drying_deadline:
            _LOGGER.info("Daikin %s: post-off drying finished — powering off", self._ip)
            # A rejected power-off keeps phase="drying" so the next poll
            # retries — the unit must not run fan-only forever.
            try:
                self._update_state(False)
            except Exception as err:
                _LOGGER.warning(
                    "Daikin %s: post-off drying power-off failed, retrying (%s)",
                    self._ip, err,
                )
                return
            self._drying_phase = None
            self._drying_deadline = None
            self._persist(None)
            self._pre_transition_mode = HVACMode.OFF
            self._hvac_mode = HVACMode.OFF  # optimistic
            return

        if self._drying_fan_pending and now >= self._drying_step_after:
            # Own request after the start has settled; a local-API write keeps
            # last_ope at 100, so it is not read as a takeover.
            try:
                self._send_attribute(
                    DaikinRequest(
                        [
                            DaikinAttribute(
                                HVAC_MODE_TO_FAN_SPEED_ATTR_NAME[HVACMode.FAN_ONLY],
                                FAN_MODE_MAP[HAFanMode.FAN_AUTO],
                                ["e_1002", "e_3001"],
                                "/dsiot/edge/adr_0100.dgc_status",
                            )
                        ]
                    ).serialize()
                )
            except Exception as err:
                _LOGGER.warning(
                    "Daikin %s: post-off drying fan Auto failed, retrying (%s)",
                    self._ip, err,
                )
                return
            self._drying_fan_pending = False
            self._fan_mode = HAFanMode.FAN_AUTO  # optimistic

    @property
    def temperature_unit(self):
        """Return the unit of measurement."""
        return UnitOfTemperature.CELSIUS

    # The max and min temps set the upper and lower bounds of the homeassistant climate control.
    # When not set, API errors arise if you request temperatures that are out of bounds
    @property
    def max_temp(self):
        """Return the maximum temperature."""
        return self._max_temp

    @property
    def min_temp(self):
        """Return the minimum temperature."""
        return self._min_temp

    @property
    def target_temperature(self):
        """Return the temperature we try to reach.

        Always return a value so the thermostat card shows the dial even when
        the unit is OFF/DRY/FAN_ONLY.
        """
        return self._target_temperature if self._target_temperature is not None else 22.0

    @property
    def target_temperature_step(self) -> float:
        """Return the supported target temperature step.

        Daikin remotes typically support 0.5°C increments.
        """
        return 0.5

    @property
    def current_temperature(self):
        return self._current_temperature

    @property
    def extra_state_attributes(self):
        return {
            "outside_temperature": self._outside_temperature,
            "runtime_today": self._runtime_today,
            "energy_today": self._energy_today
        }

    @property
    def unique_id(self):
        return self._mac

    @staticmethod
    def find_value_by_pn(data:dict, fr: str, *keys):
        data = [ x['pc'] for x in data['responses'] if x['fr'] == fr ]

        while keys:
            current_key = keys[0]
            keys = keys[1:]
            found = False
            for pcs in data:
                if pcs['pn'] == current_key:
                    if not keys:
                        return pcs['pv']
                    data = pcs['pch']
                    found = True
                    break
            if not found:
                raise Exception(f'Key {current_key} not found')

    @staticmethod
    def find_value_or_none(data: dict, fr: str, *keys):
        """Like find_value_by_pn, but returns None silently when absent."""
        try:
            return LocalDaikin.find_value_by_pn(data, fr, *keys)
        except Exception:
            return None

    @staticmethod
    def parse_timer_minutes(raw: str | None) -> int | None:
        """Decode a little-endian 16-bit hex value ("4E00" -> 78)."""
        try:
            return int.from_bytes(bytes.fromhex(raw), "little") if raw else None
        except (ValueError, TypeError):
            return None

    @staticmethod
    def try_find_value_by_pn(data: dict, fr: str, *keys):
        try:
            return LocalDaikin.find_value_by_pn(data, fr, *keys)
        except Exception as err:
            _LOGGER.warning(
                "Daikin: missing data for %s %s (%s)",
                fr,
                " -> ".join(keys),
                err,
            )
            return None


    @staticmethod
    def hex_to_temp(value: str, divisor=2) -> float:
        temp = int(value[:2], 16)
        if temp >= 128:
            temp -= 256
        return temp / divisor


    def set_temperature(self, temperature: float, **kwargs):
        _LOGGER.info("Temp change to " + str(temperature) + " requested.")
        attr_name = HVAC_TO_TEMP_HEX.get(self.hvac_mode)
        if attr_name is None:
            _LOGGER.error(f"Cannot set temperature in {self.hvac_mode} mode.")
            return

        self._target_temperature = temperature  # optimistic
        temperature_hex = format(int(temperature * 2), '02x') 
        temp_attr = DaikinAttribute(attr_name, temperature_hex, ["e_1002", "e_3001"], "/dsiot/edge/adr_0100.dgc_status")
        self._send_attribute(DaikinRequest([temp_attr]).serialize())
        self._user_takeover()

    def _send_attribute(self, request: dict) -> None:
        """Send a command to the Daikin unit. Does NOT poll for updated state afterwards
        (optimistic updates handle the UI; next poll cycle confirms)."""
        _LOGGER.info(request)
        try:
            response = requests.post(self.url, json=request, timeout=REQUEST_TIMEOUT).json()
        except RequestException as err:
            _LOGGER.error("Daikin %s: failed to send command: %s", self._ip, err)
            raise
        _LOGGER.info(response)
        if response['responses'][0]['rsc'] != 2004:
            _LOGGER.warning(
                "Daikin %s: command rejected (rsc=%s). request=%s response=%s",
                self._ip,
                response['responses'][0].get('rsc'),
                request,
                response,
            )
            raise Exception(f"An exception occured:\n{response}")

    def _update_state(self, state: bool):
        attribute = DaikinAttribute("p_01", "00" if not state else "01", ["e_1002", "e_A002"], "/dsiot/edge/adr_0100.dgc_status")
        self._send_attribute(DaikinRequest([attribute]).serialize())

    def turn_off(self):
        _LOGGER.info("Turned off")
        self._hvac_mode = HVACMode.OFF  # optimistic
        self._update_state(False)
        self._user_takeover()

    def turn_on(self):
        _LOGGER.info("Turned on")
        self._update_state(True)
        self._user_takeover()

    def get_swing_state(self, data: dict) -> str:


        # The number of zeros in the response seems strange. Don't have time to work out, so this should work
        vertical_attr_name, horizontal_attr_name = HVAC_MODE_TO_SWING_ATTR_NAMES[self.hvac_mode]
        vertical = "F" in self.find_value_by_pn(data, "/dsiot/edge/adr_0100.dgc_status", "dgc_status", "e_1002", "e_3001", vertical_attr_name)
        horizontal = "F" in self.find_value_by_pn(data, "/dsiot/edge/adr_0100.dgc_status", "dgc_status", "e_1002", "e_3001", horizontal_attr_name)

        if horizontal and vertical:
            return SWING_BOTH
        if horizontal:
            return SWING_HORIZONTAL
        if vertical:
            return SWING_VERTICAL
        
        return SWING_OFF

    @property
    def current_humidity(self) -> int:
        return self._current_humidity


    def update(self):
        """Fetch new state data for the entity."""
        payload = {
            "requests": [
                {"op": 2, "to": "/dsiot/edge/adr_0100.dgc_status?filter=pv,pt,md"},
                {"op": 2, "to": "/dsiot/edge/adr_0200.dgc_status?filter=pv,pt,md"},
                {"op": 2, "to": "/dsiot/edge/adr_0100.i_power.week_power?filter=pv,pt,md"}
            ]
        }

        try:
            response = requests.post(self.url, json=payload, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
        except RequestException as err:
            _LOGGER.warning("Daikin %s: update failed (%s), will retry next poll", self._ip, err)
            self._available = False
            return

        data = response.json()

        try:
            # Set the HVAC mode.
            is_off_raw = self.try_find_value_by_pn(
                data,
                "/dsiot/edge/adr_0100.dgc_status",
                "dgc_status",
                "e_1002",
                "e_A002",
                "p_01",
            )
            is_off = (is_off_raw == "00") if is_off_raw is not None else None

            mode_raw = self.try_find_value_by_pn(
                data,
                "/dsiot/edge/adr_0100.dgc_status",
                "dgc_status",
                "e_1002",
                "e_3001",
                "p_01",
            )
            if is_off is True:
                self._hvac_mode = HVACMode.OFF
            elif mode_raw in MODE_MAP:
                self._hvac_mode = MODE_MAP[mode_raw]
            elif mode_raw is not None:
                _LOGGER.warning("Daikin %s: unknown hvac mode code %s", self._ip, mode_raw)

            ope_type = self.find_value_or_none(
                data,
                "/dsiot/edge/adr_0100.dgc_status",
                "dgc_status",
                "last_ope",
                "type",
            )
            self._last_ope_type = ope_type if isinstance(ope_type, int) else None
            self._off_timer_minutes = self.parse_timer_minutes(
                self.find_value_or_none(
                    data, "/dsiot/edge/adr_0100.dgc_status", "dgc_status",
                    "e_1002", "e_3003", "p_3B",
                )
            )

            outside_raw = self.try_find_value_by_pn(
                data,
                '/dsiot/edge/adr_0200.dgc_status',
                'dgc_status',
                'e_1003',
                'e_A00D',
                'p_01',
            )
            if outside_raw is not None:
                self._outside_temperature = self.hex_to_temp(outside_raw)

            # Update target temperature.
            # When OFF/DRY/FAN_ONLY, try to preserve the last known target temp so the
            # thermostat dial still shows.
            name = HVAC_TO_TEMP_HEX.get(self._hvac_mode)
            if name is not None:
                try:
                    target_raw = self.try_find_value_by_pn(
                        data,
                        '/dsiot/edge/adr_0100.dgc_status',
                        'dgc_status',
                        'e_1002',
                        'e_3001',
                        name,
                    )
                    if target_raw is not None:
                        self._target_temperature = self.hex_to_temp(target_raw)
                except Exception:
                    _LOGGER.warning("No target temperature found, keeping previous or using fallback.")
                    if self._target_temperature is None:
                        self._target_temperature = 22.0  # default
            else:
                # Best effort: grab the cooling target temp (p_02) so the dial still has a value.
                try:
                    target_raw = self.try_find_value_by_pn(
                        data,
                        '/dsiot/edge/adr_0100.dgc_status',
                        'dgc_status',
                        'e_1002',
                        'e_3001',
                        'p_02',
                    )
                    if target_raw is not None:
                        self._target_temperature = self.hex_to_temp(target_raw)
                except Exception:
                    if self._target_temperature is None:
                        self._target_temperature = 22.0  # default fallback

            # For some reason, this hex value does not get the 'divide by 2' treatment. My only assumption as to why this might be is because the level of granularity
            # for this temperature is limited to integers. So the passed divisor is 1.
            current_temp_raw = self.try_find_value_by_pn(
                data,
                '/dsiot/edge/adr_0100.dgc_status',
                'dgc_status',
                'e_1002',
                'e_A00B',
                'p_01',
            )
            if current_temp_raw is not None:
                self._current_temperature = self.hex_to_temp(current_temp_raw, divisor=1)

            # If we cannot find a name for this hvac_mode's fan speed, it is automatic. This is the case for dry.
            fan_mode_key_name = HVAC_MODE_TO_FAN_SPEED_ATTR_NAME.get(self._hvac_mode)
            if fan_mode_key_name is not None:
                hex_value = self.try_find_value_by_pn(
                    data,
                    "/dsiot/edge/adr_0100.dgc_status",
                    "dgc_status",
                    "e_1002",
                    "e_3001",
                    fan_mode_key_name,
                )
                if hex_value is not None and hex_value in REVERSE_FAN_MODE_MAP:
                    self._fan_mode = REVERSE_FAN_MODE_MAP[hex_value]
                elif hex_value is not None:
                    _LOGGER.warning("Daikin %s: unknown fan mode code %s", self._ip, hex_value)
            else:
                self._fan_mode = HAFanMode.FAN_AUTO

            humidity_raw = self.try_find_value_by_pn(
                data,
                '/dsiot/edge/adr_0100.dgc_status',
                'dgc_status',
                'e_1002',
                'e_A00B',
                'p_02',
            )
            if humidity_raw is not None:
                self._current_humidity = int(humidity_raw, 16)

            if not self.hvac_mode == HVACMode.OFF:
                try:
                    self._swing_mode = self.get_swing_state(data)
                except Exception as err:
                    _LOGGER.warning("Daikin %s: swing state unavailable (%s)", self._ip, err)

            energy_datas = self.try_find_value_by_pn(
                data,
                '/dsiot/edge/adr_0100.i_power.week_power',
                'week_power',
                'datas',
            )
            if energy_datas:
                self._energy_today = energy_datas[-1]

            runtime_today = self.try_find_value_by_pn(
                data,
                '/dsiot/edge/adr_0100.i_power.week_power',
                'week_power',
                'today_runtime',
            )
            if runtime_today is not None:
                self._runtime_today = runtime_today

            # The state machine never raises: it catches its own command rejections and
            # retries on the next poll, so a failed command does not take a
            # healthy, fully-parsed entity offline.
            self._process_post_off_drying(now=time())

            # Successfully parsed — mark available
            self._available = True

        except Exception as err:
            _LOGGER.warning("Daikin %s: failed to parse update response (%s)", self._ip, err)
            self._available = False
