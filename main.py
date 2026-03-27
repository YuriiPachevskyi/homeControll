from ruamel.yaml import YAML
import i2c_controller
import mqtt_controller
import settings
import time
from datetime import datetime
import builtins

import logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

yaml = YAML()
switchDict = {}
inputDict = {}
switches = yaml.load(open(settings.confSwitchesFile))
i2CWriteController = i2c_controller.I2CWriteController()

for item in switches:
    sw = item["switch"]
    key = sw["command_topic"].split("/")[-1]
    switchDict[key] = sw["state_off"]

def onMQTTEvent(id, state):
    logger.info("MQTT Event id=%s state=%s", id, state)
    if id in switchDict:
        changeSwitchState(id, state)
    else:
        logger.warning("onMQTTEvent: id %s not existing", id)

def onInputEvent(key, delay):
    prefix = str(key)[:3]
    pins = int(key[3:])
    switchesIdList = None
    logger.info("Input Event prefix=%s pins=%s delay=%s", prefix, bin(pins)[2:].zfill(8), delay)

    for i in range(8):
        if pins & (1 << i):
            key = prefix + str(i)
            if delay < 4:
                switchesIdList = inputDict[key].onShortId()
            elif delay < 9:
                switchesIdList = inputDict[key].onLongId()
            else:
                switchesIdList = inputDict[key].onLonglId()
    for id in switchesIdList:
        changeSwitchState(str(id), "TRIGGER")

def changeSwitchState(id, state):
    i2cDevice = int(id[:1])
    i2cRegister = int(id[1:-1])
    i2cPin = int(id[-1:])

    if state == "ON":
        i2CWriteController.set_enabled(i2cDevice, i2cRegister, i2cPin)
    elif state == "OFF":
        i2CWriteController.set_disabled(i2cDevice, i2cRegister, i2cPin)
    elif state == "TRIGGER":
        if i2CWriteController.trigger_value(i2cDevice, i2cRegister, i2cPin):
            state = "OFF"
        else:
            state = "ON"
    mqttController.publish(id, state)

mqttController = mqtt_controller.MQTTController(settings.mqttMainPath, onMQTTEvent)
i2c_controller.I2CReadController(inputDict, onInputEvent).i2c_read()

