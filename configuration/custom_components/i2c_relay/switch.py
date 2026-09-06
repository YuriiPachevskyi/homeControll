"""Switch platform for direct I2C relay control (PCF8574-style expanders).

YAML example (drop-in replacement for the MQTT switches in switches.yaml):

switch:
  - platform: i2c_relay
    switches:
      - name: "1560 Boiler ten 0.8 kWh"
        id: "1566"
      - name: "1561 Boiler ten 1.2 kWh"
        id: "1561"
"""
from __future__ import annotations

from datetime import timedelta
import logging

import voluptuous as vol

import homeassistant.helpers.config_validation as cv
from homeassistant.components import persistent_notification
from homeassistant.components.switch import PLATFORM_SCHEMA, SwitchEntity
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType

from .bus import I2CBusManager, parse_id

_LOGGER = logging.getLogger(__name__)

CONF_SWITCHES = "switches"
CONF_ID = "id"
CONF_INVERT = "invert"

SCAN_INTERVAL = timedelta(seconds=15)

SWITCH_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_NAME): cv.string,
        vol.Required(CONF_ID): cv.string,
        vol.Optional(CONF_INVERT, default=False): cv.boolean,
    }
)

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Required(CONF_SWITCHES): vol.All(cv.ensure_list, [SWITCH_SCHEMA]),
    }
)


def setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None,
) -> None:
    entities = []
    for sw in config[CONF_SWITCHES]:
        bus_idx, addr, pin = parse_id(sw[CONF_ID])
        if bus_idx is None:
            _LOGGER.error("Skipping switch %s: invalid id %s", sw[CONF_NAME], sw[CONF_ID])
            continue
        entities.append(
            I2CRelaySwitch(sw[CONF_NAME], sw[CONF_ID], bus_idx, addr, pin, sw[CONF_INVERT])
        )
    add_entities(entities, True)


class I2CRelaySwitch(SwitchEntity):
    """A single relay output on a PCF8574-style I2C expander."""

    _attr_should_poll = True

    def __init__(self, name, raw_id, bus_idx, addr, pin, invert):
        self._attr_name = name
        self._attr_unique_id = f"i2c_relay_{raw_id}"
        self._raw_id = raw_id
        self._bus_idx = bus_idx
        self._addr = addr
        self._pin = pin
        self._invert = invert
        self._attr_is_on = None
        self._attr_available = True

    def _raw_to_display(self, raw_on: bool) -> bool:
        return (not raw_on) if self._invert else raw_on

    def _display_to_raw(self, display_on: bool) -> bool:
        return (not display_on) if self._invert else display_on

    def update(self) -> None:
        raw_on = I2CBusManager.is_pin_on(self._bus_idx, self._addr, self._pin)
        if raw_on is None:
            if self._attr_available:
                persistent_notification.create(
                    self.hass,
                    f"Switch **{self._attr_name}** (id `{self._raw_id}` = bus {self._bus_idx}, "
                    f"addr {self._addr}, pin {self._pin}) stopped responding on I2C. "
                    f"Check wiring/address, or run `i2cdetect -y {self._bus_idx}` on the host "
                    f"to confirm the device is present. See the log for the exact I2C error.",
                    title="I2C relay unavailable",
                    notification_id=f"i2c_relay_{self._raw_id}",
                )
            self._attr_available = False
            return
        if not self._attr_available:
            persistent_notification.dismiss(self.hass, f"i2c_relay_{self._raw_id}")
        self._attr_available = True
        self._attr_is_on = self._raw_to_display(raw_on)

    def turn_on(self, **kwargs) -> None:
        if I2CBusManager.set_pin(self._bus_idx, self._addr, self._pin, self._display_to_raw(True)):
            self._attr_is_on = True
            self._attr_available = True

    def turn_off(self, **kwargs) -> None:
        if I2CBusManager.set_pin(self._bus_idx, self._addr, self._pin, self._display_to_raw(False)):
            self._attr_is_on = False
            self._attr_available = True
