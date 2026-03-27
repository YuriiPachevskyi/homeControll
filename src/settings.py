from pathlib import Path
import os

home = str(Path.home())
confSwitchesFile = os.getenv('CONFIG_PATH', '/home/yurii/docker/homeControll/configuration/switches.yaml')

# Timings in seconds
DEBOUNCE_TIME = 0.05    # Ignore pulses shorter than 50ms (noise)
SHORT_PRESS_TIME = 0.6  # Up to 600ms is a Short Press
LONG_PRESS_TIME = 1.5   # Between 600ms and 1.5s is a Long Press, above is LongL

i2cMaxValue = 255
i2cReadTimeout = 0.08
mqttMainPath = "home/main/#"
mqttStatusPath = "home/status/main/#"
serverAddressAndPort = "http://localhost:8123"
serverAddress = "localhost"
