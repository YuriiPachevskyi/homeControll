import time
import i2c_pin
import i2c_controller as i2c
import json
from pprint import pprint

switchMap = {}

with open('/home/yuso/work/controllService/conf.json') as conf:
    data = json.load(conf)

switch = data["switch"]
inputs = data["inputs"]

for i in range(len(switch)):
    switchMap[switch[i]["id"]] = i2c_pin.I2CPin(int(switch[i]["i2cDevice"]), \
    int(switch[i]["i2cReg"]), int(switch[i]["pin"]), switch[i]["path"])

#def isEqualPin(value, number):
#    return ~value & (1 << number)

def onEvent(key, delay):
    print("onEvent key", key, "delay", delay)

    #if isEqualPin(key, 7):
    #    i2cPin1.trigger_value()

i2c.I2CReadController(inputs, onEvent)

while not 0: time.sleep(0.1)
