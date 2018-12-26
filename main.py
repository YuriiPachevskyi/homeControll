import time
import settings
import i2c_controller as i2c
import mqtt_controller as mqtt
import json
from ruamel import yaml

switchDict = {}
inputDict = {}
inputs = json.load(open(settings.inputsConfFile))
switches = yaml.safe_load(open(settings.switchesConfFile))
i2CWriteController = i2c.I2CWriteController()

for i in range(len(switches)):
    key = switches[i]['command_topic'][-4:]
    switchDict[key] = switches[i]["state_" + str(key)]

for i in range(len(inputs)):
    inputDict[inputs[i]["id"]] = i2c.I2CInputDevice(inputs[i]["onShort"], inputs[i]["onLong"], inputs[i]["onLongLong"])

def onMQTTEvent(id, state):
    setSwitchState(id, state)

def onInputEvent(key, delay):
    prefix = str(key)[:3]
    pins = int(key[3:])
    print("prefix", prefix, "pins", bin(pins)[2:].zfill(8), "delay", delay)
    for i in range(8):
        if pins & (1 << i):
            key = prefix + str(i)
            if delay < 4:
                triggerState(inputDict[key].get_on_short_id())
            elif delay < 9:
                triggerState(inputDict[key].get_on_long_id())
            else:
                triggerState(inputDict[key].get_on_longl_id())

def triggerState(switchesId):
    for id in switchesId:
        i2cDevice = int(str(id)[:1])
        i2cRegister = int(str(id)[1:-1])
        i2cPin = int(str(id)[-1:])
        i2CWriteController.trigger_value(i2cDevice, i2cRegister, i2cPin)

def setSwitchState(id, state):
    i2cDevice = int(id[:1])
    i2cRegister = int(id[1:-1])
    i2cPin = int(id[-1:])

    if state == "ON":
        i2CWriteController.set_enabled(i2cDevice, i2cRegister, i2cPin)
    elif state == "OFF":
        i2CWriteController.set_disabled(i2cDevice, i2cRegister, i2cPin)

def restoreSwitchesState():
    for key in switchDict:
        setSwitchState(key, switchDict[key])

mqttController = mqtt.MQTTController("home/main/#", onMQTTEvent)
restoreSwitchesState()
i2c.I2CReadController(inputDict, onInputEvent)

while not 0: time.sleep(0.1)
