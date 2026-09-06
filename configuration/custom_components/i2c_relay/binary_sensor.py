"""Binary sensor platform for I2C-connected physical buttons/toggles.

Reports raw pin state only (pressed/not pressed) - press-duration
classification (short/long/very long) lives in automations, see the
i2c_relay/button_press blueprint.

YAML example:

binary_sensor:
  - platform: i2c_relay
    inputs:
      - name: "Kitchen wall button"
        id: "1200"
"""
from __future__ import annotations

from datetime import timedelta
import logging

import voluptuous as vol

import homeassistant.helpers.config_validation as cv
from homeassistant.components import persistent_notification
from homeassistant.components.binary_sensor import PLATFORM_SCHEMA, BinarySensorEntity
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType

from .bus import I2CBusManager, parse_id

_LOGGER = logging.getLogger(__name__)

CONF_INPUTS = "inputs"
CONF_ID = "id"
CONF_INVERT = "invert"

SCAN_INTERVAL = timedelta(seconds=0.2)

INPUT_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_NAME): cv.string,
        vol.Required(CONF_ID): cv.string,
        vol.Optional(CONF_INVERT, default=False): cv.boolean,
    }
)

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Required(CONF_INPUTS): vol.All(cv.ensure_list, [INPUT_SCHEMA]),
    }
)


def setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None,
) -> None:
    entities = []
    for inp in config[CONF_INPUTS]:
        bus_idx, addr, pin = parse_id(inp[CONF_ID])
        if bus_idx is None:
            _LOGGER.error("Skipping input %s: invalid id %s", inp[CONF_NAME], inp[CONF_ID])
            continue
        entities.append(
            I2CInputSensor(inp[CONF_NAME], inp[CONF_ID], bus_idx, addr, pin, inp[CONF_INVERT])
        )
    add_entities(entities, True)


class I2CInputSensor(BinarySensorEntity):
    """A single physical contact (button/toggle) on a PCF8574-style I2C expander."""

    _attr_should_poll = True

    def __init__(self, name, raw_id, bus_idx, addr, pin, invert):
        self._attr_name = name
        self._attr_unique_id = f"i2c_relay_input_{raw_id}"
        self._raw_id = raw_id
        self._bus_idx = bus_idx
        self._addr = addr
        self._pin = pin
        self._invert = invert
        self._attr_is_on = None
        self._attr_available = True

    def update(self) -> None:
        raw_on = I2CBusManager.is_pin_on(self._bus_idx, self._addr, self._pin)
        if raw_on is None:
            if self._attr_available:
                persistent_notification.create(
                    self.hass,
                    f"Input **{self._attr_name}** (id `{self._raw_id}` = bus {self._bus_idx}, "
                    f"addr {self._addr}, pin {self._pin}) stopped responding on I2C. "
                    f"Check wiring/address, or run `i2cdetect -y {self._bus_idx}` on the host "
                    f"to confirm the device is present. See the log for the exact I2C error.",
                    title="I2C input unavailable",
                    notification_id=f"i2c_relay_input_{self._raw_id}",
                )
            self._attr_available = False
            return
        if not self._attr_available:
            persistent_notification.dismiss(self.hass, f"i2c_relay_input_{self._raw_id}")
        self._attr_available = True
        if self._invert:
            self._attr_is_on = not raw_on
            return
        self._attr_is_on = raw_on
