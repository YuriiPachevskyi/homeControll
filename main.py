import time
import i2c_pin
import i2c_input
import i2c_controller as i2c
import state_controller as state
import json
from pprint import pprint

with open('/home/yuso/work/controllService/conf.json') as confFile:
    data = json.load(confFile)

switchDict = {}
inputDict = {}

switch = data["switch"]
inputs = data["inputs"]

for i in range(len(switch)):
    switchDict[switch[i]["id"]] = i2c_pin.I2CPin(int(switch[i]["i2cDevice"]), \
    int(switch[i]["i2cReg"]), int(switch[i]["pin"]), switch[i]["path"])

for i in range(len(inputs)):
    inputDict[inputs[i]["id"]] = i2c_input.I2CInputDevice(inputs[i]["onShortSwId"], \
    inputs[i]["onLongSwId"], inputs[i]["onLongLongSwId"])

def triggerSwitchState(switchesId):
    for swId in switchesId:
        switchDict[str(swId)].trigger_value()

def onPinStateChanged(prefix, pins, delay):
    print("prefix", prefix, "pins", bin(pins)[2:].zfill(8), "delay", delay)
    for i in range(8):
        if pins & (1 << i):
            key = prefix + str(i)
            if delay < 4:
                triggerSwitchState(inputDict[key].get_on_short_id())
            elif delay < 9:
                triggerSwitchState(inputDict[key].get_on_long_id())
            else:
                triggerSwitchState(inputDict[key].get_on_longl_id())

def onEvent(key, delay):
    onPinStateChanged(key[:3], int(key[3:]), delay)

i2c.I2CReadController(inputs, onEvent)

while not 0: time.sleep(0.1)
