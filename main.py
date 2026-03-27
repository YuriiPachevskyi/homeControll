from ruamel.yaml import YAML
from subprocess import call
import i2c_controller
import mqtt_controller
import settings
import time
from datetime import datetime
import builtins

yaml = YAML()
switchDict = {}
inputDict = {}
switches = yaml.load(open(settings.confSwitchesFile))
i2CWriteController = i2c_controller.I2CWriteController()

def print(*args, **kwargs):
    builtins.print(datetime.now().strftime("%Y-%m-%d %H:%M:%S"), *args, **kwargs, flush=True)

for item in switches:
    sw = item["switch"]
    key = sw["command_topic"].split("/")[-1]
    switchDict[key] = sw["state_off"]

def onMQTTEvent(id, state):
    print("id", id, "state", state)
    if id in switchDict:
        changeSwitchState(id, state)
    else:
        print("onMQTTEvent not existing id = ", id)

def onInputEvent(key, delay):
    prefix = str(key)[:3]
    pins = int(key[3:])
    switchesIdList = None
    print("prefix", prefix, "pins", bin(pins)[2:].zfill(8), "delay", delay)

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
