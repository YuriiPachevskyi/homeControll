import json
import os
from ruamel.yaml import YAML
import i2c_controller
import mqtt_controller
import settings
from models import I2CInputDevice

import logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

yaml = YAML()
switchDict = {}
inputDict = {}

with open(settings.confSwitchesFile, 'r') as f:
    switches = yaml.load(f)

i2CWriteController = i2c_controller.I2CWriteController()

for item in switches:
    sw = item["switch"]
    key = sw["command_topic"].split("/")[-1]
    switchDict[key] = sw["state_off"]

# Load input devices mapping from JSON file
if os.path.exists(settings.confInputsFile):
    with open(settings.confInputsFile, 'r') as f:
        inputs_data = json.load(f)
        for inp in inputs_data:
            inputDict[str(inp["id"])] = I2CInputDevice(
                onShort=[str(x) for x in inp.get("onShort", [])],
                onLong=[str(x) for x in inp.get("onLong", [])],
                onLongL=[str(x) for x in inp.get("onLongLong", [])]
            )

def onMQTTEvent(id, state):
    logger.info("MQTT Event id=%s state=%s", id, state)
    if id in switchDict:
        changeSwitchState(id, state)
    else:
        logger.warning("onMQTTEvent: id %s not existing", id)

def onInputEvent(key, delay):
    parts = key.split(":")
    device, register, pins = parts[0], parts[1], int(parts[2])

    logger.info("Input Event device=%s reg=%s pins=%s delay=%s", device, register, bin(pins)[2:].zfill(8), delay)

    for i in range(8):
        if pins & (1 << i):
            # YAML: [Device][Register][Pin]
            input_key = f"{device}{register}{i}"
            if input_key not in inputDict:
                logger.warning("No config for input key: %s", input_key)
                continue

            sw_list = []
            if delay < settings.DEBOUNCE_TIME:
                continue  # Ignore physical contact bounce
            elif delay < settings.SHORT_PRESS_TIME:
                sw_list = inputDict[input_key].onShortId()
            elif delay < settings.LONG_PRESS_TIME:
                sw_list = inputDict[input_key].onLongId()
            else:
                sw_list = inputDict[input_key].onLonglId()

            for sw_id in sw_list:
                if str(sw_id) not in switchDict:
                    logger.error("Input %s refers to non-existent switch ID: %s", input_key, sw_id)
                    continue
                changeSwitchState(str(sw_id), "TRIGGER")

def parse_switch_id(sw_id):
    try:
        return int(sw_id[0]), int(sw_id[1:-1]), int(sw_id[-1])
    except (ValueError, IndexError):
        logger.error("Invalid ID format: %s", sw_id)
        return None, None, None

def changeSwitchState(id, state):
    i2cDevice, i2cRegister, i2cPin = parse_switch_id(id)
    if i2cDevice is None: return

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

try:
    if inputDict:
        i2c_reader = i2c_controller.I2CReadController(inputDict, onInputEvent)
        i2c_reader.i2c_read()
    else:
        logger.warning("No inputs configured in %s. I2C monitoring skipped.", settings.confInputsFile)
except KeyboardInterrupt:
    logger.info("Stopping homeControll...")
