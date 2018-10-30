import time
import i2c_pin
import settings
import smbus2 as smbus

class I2CController:
    bus = smbus.SMBus(settings.i2cDevice)

    def __init__(self, register):
        self.register = register

class I2CReadController(I2CController):
    expanderState = {}

    def __init__(self, register, callback):
        I2CController.__init__(self, register)
        self.callback = callback
        self.i2c_read()

    def i2c_read(self):
        while True:
            key = self.bus.read_byte(self.register)
            if key == settings.i2cMaxValue:
                if not self.expanderState:
                    time.sleep(settings.i2cReadTimeout)
                    continue
                else:
                    for key in self.expanderState:
                        self.callback(key, self.expanderState[key])
                    self.expanderState.clear()
            else:
                self.expanderState[key] = self.expanderState.get(key, 0) + 1
            time.sleep(settings.i2cReadTimeout)

class I2CWriteController(I2CController):

    def __init__(self, register, pin):
        I2CController.__init__(self, register)
        self.pin = pin

    def set_enabled(self):
        value = self.bus.read_byte(self.register) & ~(1 << self.pin)
        self.bus.write_byte(self.register, value)

    def set_disabled(self):
        value = self.bus.read_byte(self.register) | (1 << self.pin)
        self.bus.write_byte(self.register, value)

