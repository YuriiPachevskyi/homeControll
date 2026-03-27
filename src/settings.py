from pathlib import Path
import os

home = str(Path.home())
confSwitchesFile = os.getenv('CONFIG_PATH', '/home/yurii/docker/homeControll/configuration/switches.yaml')

SHORT_PRESS_TICKS = 4
LONG_PRESS_TICKS = 9

i2cMaxValue = 255
i2cReadTimeout = 0.08
mqttMainPath = "home/main/#"
mqttStatusPath = "home/status/main/#"
serverAddressAndPort = "http://localhost:8123"
serverAddress = "localhost"
