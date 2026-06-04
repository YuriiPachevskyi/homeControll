"""."""

import logging

from typing import Any
from math import floor

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_COLOR_TEMP_KELVIN,
    ATTR_EFFECT,
    ATTR_HS_COLOR,
    ATTR_RGBW_COLOR,
    ATTR_RGBWW_COLOR,
    ATTR_WHITE,
    DEFAULT_MAX_KELVIN,
    DEFAULT_MIN_KELVIN,
    EFFECT_OFF,
    ColorMode,
    LightEntity,
    LightEntityFeature,
)

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .config_entry import New_NameConfigEntry
from .coordinator import IotDeviceCoordinator
from .device import Device
from .device_features import DeviceFeatureEnum
from .tcl_entity_base import TclEntityBase

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: New_NameConfigEntry,
    async_add_entities: AddEntitiesCallback,
):
    """Set up the Light Sensors."""
    coordinator = config_entry.runtime_data.coordinator

    lights = []
    for device in config_entry.devices:
        if DeviceFeatureEnum.LIGHT_AMBIENT in device.supported_features:
            lights.append(
                LightWithBrightesOnlyHandler(
                    hass=hass,
                    coordinator=coordinator,
                    device=device,
                    type="AmbitentLight",
                    name="Ambitent Light",
                    light_feature=DeviceFeatureEnum.LIGHT_AMBIENT,
                )
            )

    async_add_entities(lights)


class LightWithBrightesOnlyHandler(
    TclEntityBase,
    LightEntity,
):
    _attr_has_entity_name = True
    _attr_name = None

    _attr_max_color_temp_kelvin = DEFAULT_MAX_KELVIN
    _attr_min_color_temp_kelvin = DEFAULT_MIN_KELVIN

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: IotDeviceCoordinator,
        device: Device,
        type: str,
        name: str,
        light_feature: str,
    ) -> None:
        """Initialize the light."""
        TclEntityBase.__init__(self, coordinator, type, name, device)
        self.light_feature = light_feature
        if self.light_feature == DeviceFeatureEnum.LIGHT_AMBIENT:
            self._attr_brightness = self.device.data.ambient_light_brightness
            self._attr_is_on = self.device.data.ambient_light_power_switch
            self._attr_color_mode = ColorMode.BRIGHTNESS
            self._attr_supported_color_modes = {ColorMode.BRIGHTNESS}

    @property
    def brightness(self) -> int | None:
        self.device = self.coordinator.get_device_by_id(self.device.device_id)
        brightness = 0
        if self.light_feature == DeviceFeatureEnum.LIGHT_AMBIENT:
            brightness = self.device.data.ambient_light_brightness
            # convert brightnes 0-100 % to HA 0-255
            brightness = 255 if brightness == 100 else floor(brightness * 255 / 99.0)
        return int(brightness)

    @property
    def is_on(self) -> int | None:
        self.device = self.coordinator.get_device_by_id(self.device.device_id)
        is_on = 0
        if self.light_feature == DeviceFeatureEnum.LIGHT_AMBIENT:
            is_on = self.device.data.ambient_light_power_switch
        return is_on == 1

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the light on."""
        self._attr_is_on = True

        if ATTR_BRIGHTNESS in kwargs:
            self._attr_brightness = kwargs[ATTR_BRIGHTNESS]

        if self.light_feature == DeviceFeatureEnum.LIGHT_AMBIENT:
            # convert HA 0-255 brightnes to 0-100 %
            brightness = int(floor(self._attr_brightness * 100 / 255.0))
            desired_state = {
                "ambientLight": {
                    "powerSwitch": 1,
                    "brightness": brightness,
                }
            }
            await self.coordinator.get_aws_iot().async_set_desired_state(
                self.device.device_id, desired_state
            )
        await self.coordinator.async_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the light off."""
        self._attr_is_on = False

        if self.light_feature == DeviceFeatureEnum.LIGHT_AMBIENT:
            desired_state = {"ambientLight": {"powerSwitch": 0}}
            await self.coordinator.get_aws_iot().async_set_desired_state(
                self.device.device_id, desired_state
            )
        await self.coordinator.async_refresh()
