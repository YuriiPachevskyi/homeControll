"""I2C relay integration - direct PCF8574-style I/O expander control, replaces the MQTT/systemd bridge."""

DOMAIN = "i2c_relay"


async def async_setup(hass, config):
    return True
