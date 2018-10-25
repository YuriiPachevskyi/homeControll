import time
import smbus2 as smbus

class I2CController:
    bus = smbus.SMBus(1)

    def __init__(self, register):
        self.register = register

class I2CReadController(I2CController):

    def __init__(self, register):
        I2CController.__init__(self, register)

    def i2c_read(self):
        while not 0:
            value = self.bus.read_byte(self.register)
            print("value = ", value)
            time.sleep(0.05)

class I2CPinController(I2CController):

    def __init__(self, register):
        I2CController.__init__(self, register)
        self.pin = pin

    def set_i2c_enabled(self):
        value = self.bus.read_byte(self.register) & (0xFF ^ self.pin)
        self.bus.write_byte(self.register, 0)

    def set_i2c_disabled(self):
        value = self.bus.read_byte(self.register) | self.pin
        self.bus.write_byte(self.register, value)
