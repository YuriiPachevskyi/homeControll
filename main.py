import time
import i2c_pin
import i2c_controller as i2c
import json
from pprint import pprint

class I2CInputDevice:
    def __init__(self, onShort, onLong, onLongL):
        self.onShort = onShort
        self.onLong = onLong
        self.onLongL = onLongL

    def get_on_short_id(self):
        return self.onShort

    def get_on_long_id(self):
        return self.onLong

    def get_on_longl_id(self):
        return self.onLongL

with open('/home/yuso/work/controllService/conf.json') as conf:
    data = json.load(conf)

switchDict = {}
inputDict = {}

switch = data["switch"]
inputs = data["inputs"]

for i in range(len(switch)):
    switchDict[switch[i]["id"]] = i2c_pin.I2CPin(int(switch[i]["i2cDevice"]), \
    int(switch[i]["i2cReg"]), int(switch[i]["pin"]), switch[i]["path"])

for i in range(len(inputs)):
    inputDict[inputs[i]["id"]] = I2CInputDevice(inputs[i]["onShortSwId"], \
    inputs[i]["onLongSwId"], inputs[i]["onLongLongSwId"])

def triggerSwitches(switchesId):
    for swId in switchesId:
        switchDict[str(swId)].trigger_value()

def onPinsChanged(prefix, pins, delay):
    print("prefix", prefix, "pins", bin(pins)[2:].zfill(8), "delay", delay)
    for i in range(8):
        if pins & (1 << i):
            key = prefix + str(i)
            if delay < 4:
                triggerSwitches(inputDict[key].get_on_short_id())
            elif delay < 9:
                triggerSwitches(inputDict[key].get_on_long_id())
            else:
                triggerSwitches(inputDict[key].get_on_longl_id())

def onEvent(key, delay):
    onPinsChanged(key[:3], int(key[3:]), delay)

i2c.I2CReadController(inputs, onEvent)

while not 0: time.sleep(0.1)
