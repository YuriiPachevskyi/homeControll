import time
import settings
import i2c_controller as i2c
import mqtt_controller as mqtt
import state_controller as state
import json
from ruamel import yaml
from subprocess import call

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
                triggerState(inputDict[key].onShortId())
            elif delay < 9:
                triggerState(inputDict[key].onLongId())
            else:
                triggerState(inputDict[key].onLonglId())

def triggerState(switchesId):
    for id in switchesId:
        i2cDevice = int(str(id)[:1])
        i2cRegister = int(str(id)[1:-1])
        i2cPin = int(str(id)[-1:])
        if i2CWriteController.trigger_value(i2cDevice, i2cRegister, i2cPin):
            mqttController.publish(str(id), "OFF")
        else:
            mqttController.publish(str(id), "ON")

def setSwitchState(id, state):
    i2cDevice = int(id[:1])
    i2cRegister = int(id[1:-1])
    i2cPin = int(id[-1:])

    if state == "ON":
        i2CWriteController.set_enabled(i2cDevice, i2cRegister, i2cPin)
    elif state == "OFF":
        i2CWriteController.set_disabled(i2cDevice, i2cRegister, i2cPin)
    mqttController.publish(id, state)

def restoreSwitchesState():
    for key in switchDict:
        setSwitchState(key, switchDict[key])

mqttController = mqtt.MQTTController("home/main/#", onMQTTEvent)
state.UiStateUpdateThread("home/status/main/#", switchDict, mqttController).start()
state.FileStateBackupThread("home/status/main/#", switchDict).start()
restoreSwitchesState()
i2c.I2CReadController(inputDict, onInputEvent).i2c_read()
