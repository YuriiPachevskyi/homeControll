import time
import i2c_pin
import i2c_controller as i2c
import json
from pprint import pprint

switchsMap = {}

#########################################
with open('/home/yuso/work/controllService/conf.json') as conf:
    data = json.load(conf)

for item in range(len(data["switchs"])):
    print("item ", data["switchs"][item]["name"])
    switchsMap[data["switchs"][item]["id"]] = i2c_pin.I2CPin(\
    int(data["switchs"][item]["i2cDevice"]), \
    int(data["switchs"][item]["i2cReg"]), \
    int(data["switchs"][item]["pin"]), \
    data["switchs"][item]["path"])
##########################################

print(data["input"])


def isEqualPin(value, number):
    return ~value & (1 << number)

def onEvent(key, value):
    if isEqualPin(key, 7):
        i2cPin1.trigger_value()

readController = i2c.I2CReadController(1, 0x21, onEvent)

while not 0: time.sleep(0.1)
