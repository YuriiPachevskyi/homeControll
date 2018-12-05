import time
import i2c_pin
import i2c_controller as i2c
import json
from pprint import pprint

switchsMap = {}

i2cPin1 = i2c_pin.I2CPin(1, 0x20, 0, "home/bedroom/switch1")
i2cPin2 = i2c_pin.I2CPin(1, 0x20, 1, "home/bedroom/switch2")
i2cPin3 = i2c_pin.I2CPin(1, 0x20, 2, "home/bedroom/switch3")
i2cPin4 = i2c_pin.I2CPin(1, 0x20, 3, "home/bedroom/switch4")
i2cPin5 = i2c_pin.I2CPin(1, 0x20, 4, "home/bedroom/switch5")
i2cPin6 = i2c_pin.I2CPin(1, 0x20, 5, "home/bedroom/switch6")
i2cPin7 = i2c_pin.I2CPin(1, 0x20, 6, "home/bedroom/switch7")
i2cPin8 = i2c_pin.I2CPin(1, 0x20, 7, "home/bedroom/switch8")


#########################################
with open('conf.json') as conf:
    data = json.load(conf)

print(data["switchs"][0]["id"])

for item in range(len(data["switchs"])):
    print("item ", data["switchs"][item]["name"])
    switchsMap[data["switchs"][item]["id"]] = data["switchs"][item]
##########################################
print(switchsMap)

def isEqualPin(value, number):
    return ~value & (1 << number)

def onEvent(key, value):
    if isEqualPin(key, 7):
        i2cPin1.trigger_value()
    elif isEqualPin(key, 6):
        i2cPin2.trigger_value()
    elif isEqualPin(key, 5):
        i2cPin3.trigger_value()
    elif isEqualPin(key, 4):
        i2cPin4.trigger_value()
    elif isEqualPin(key, 3):
        i2cPin5.trigger_value()
    elif isEqualPin(key, 2):
        i2cPin6.trigger_value()
    elif isEqualPin(key, 1):
        i2cPin7.trigger_value()
    elif isEqualPin(key, 0):
        i2cPin8.trigger_value()

readController = i2c.I2CReadController(1, 0x21, onEvent)




while not 0: time.sleep(0.1)
