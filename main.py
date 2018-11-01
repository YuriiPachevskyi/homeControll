import time
import i2c_pin
import i2c_controller as i2c

class I2COutManager:
    i2cPinsList = {}
    def __init__(self, register):
        self.register = register

    def activate_out_pin(self, number, path):
        self.i2cPinsList[path] = i2c_pin.I2CPin(i2c_pin.Type.OUTPUT, self.register, number, path)

i2cPin1 = i2c_pin.I2CPin(i2c_pin.Type.OUTPUT, 0x20, 0, "home/bedroom/switch1")
i2cPin2 = i2c_pin.I2CPin(i2c_pin.Type.OUTPUT, 0x20, 1, "home/bedroom/switch2")
i2cPin3 = i2c_pin.I2CPin(i2c_pin.Type.OUTPUT, 0x20, 2, "home/bedroom/switch3")
i2cPin4 = i2c_pin.I2CPin(i2c_pin.Type.OUTPUT, 0x20, 3, "home/bedroom/switch4")
i2cPin5 = i2c_pin.I2CPin(i2c_pin.Type.OUTPUT, 0x20, 4, "home/bedroom/switch5")
i2cPin6 = i2c_pin.I2CPin(i2c_pin.Type.OUTPUT, 0x20, 5, "home/bedroom/switch6")
i2cPin7 = i2c_pin.I2CPin(i2c_pin.Type.OUTPUT, 0x20, 6, "home/bedroom/switch7")
i2cPin8 = i2c_pin.I2CPin(i2c_pin.Type.OUTPUT, 0x20, 7, "home/bedroom/switch8")

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

readController = i2c.I2CReadController(0x21, onEvent)


while not 0: time.sleep(0.1)
