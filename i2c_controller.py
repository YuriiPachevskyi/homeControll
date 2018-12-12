import time
import i2c_pin
import settings
import smbus2 as smbus

class I2CController:

    def __init__(self, i2cDevice, register):
        self.register = register
        self.bus = smbus.SMBus(i2cDevice)

class I2CWriteController(I2CController):

    def __init__(self, i2cDevice, register, pin):
        I2CController.__init__(self, i2cDevice, register)
        self.pin = pin

    def set_enabled(self):
        value = self.bus.read_byte(self.register) & ~(1 << self.pin)
        self.bus.write_byte(self.register, value)

    def set_disabled(self):
        value = self.bus.read_byte(self.register) | (1 << self.pin)
        self.bus.write_byte(self.register, value)

    def trigger_value(self):
        value = self.bus.read_byte(self.register) ^ (1 << self.pin)
        self.bus.write_byte(self.register, value)
        return value & (1 << self.pin)

class I2CReadController(I2CController):
    expanderState = {}
    i2cDeviceDict1 = {}
    i2cDeviceDict2 = {}

    def __init__(self, inputsMap, callback):
        self.callback = callback
        self.init_inputs(inputsMap)
        self.bus1 = smbus.SMBus(1)
        self.bus2 = smbus.SMBus(2)
        self.i2c_read()

    def init_inputs(self, inputs):
        for i in range(len(inputs)):
            key = int(inputs[i]["i2cReg"])
            pin = int(inputs[i]["pin"])
            if int(inputs[i]["i2cDevice"]) == 1 :
                self.i2cDeviceDict1[key] = self.i2cDeviceDict1.get(key, 0) | (1 << pin)
                print("key", key, "pin:", pin, "value", self.i2cDeviceDict1[key])
            elif int(inputs[i]["i2cDevice"]) == 2 :
                self.i2cDeviceDict2.append(int(inputs[i]["i2cReg"]))

    def is_input_state_changed(self, mask, value):
        return (value & mask) ^ mask

    def try_to_notify(self, targetKey):
        keyForNotify = None
        for key in self.expanderState:
            if key[1:3] == targetKey:
                keyForNotify = key
        if keyForNotify != None:
            self.callback(key, self.expanderState[key])
            self.expanderState.pop(key, None)

    def i2c_device_read(self, i2cDevice):
        if i2cDevice == 1:
            bus = self.bus1
            i2cDeviceDict = self.i2cDeviceDict1
        if i2cDevice == 2:
            bus = self.bus2
            i2cDeviceDict = self.i2cDeviceDict2

        for key in i2cDeviceDict:
            modifiedPins = self.is_input_state_changed(i2cDeviceDict[key], bus.read_byte(key))

            if not modifiedPins:
                if self.expanderState:
                    self.try_to_notify(str(key))
            else:
                exStKey = "1" + str(key) + str(modifiedPins)
                self.expanderState[exStKey] = self.expanderState.get(exStKey, 0) + 1

    def i2c_read(self):
        while True:
            self.i2c_device_read(1)
            self.i2c_device_read(2)
            time.sleep(settings.i2cReadTimeout)

