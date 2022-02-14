from pathlib import Path

home = str(Path.home())
confInputsFile = '/home/yuso/homeControll/scripts/configuration/inputs.json'
confSwitchesFile = '/home/yuso/homeControll/switches.yaml'
confSwitchesStateFile = '/home/yuso/homeControll/scripts/configuration/switches_state.yaml'
i2cMaxValue = 255
i2cReadTimeout = 0.08
mqttMainPath = "home/main/#"
mqttStatusPath = "home/status/main/#"
serverAddressAndPort = "http://localhost:8123"
serverAddress = "localhost"

