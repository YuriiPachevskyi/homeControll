from enum import Enum
import i2c_controller as i2c
import mqtt_controller as mqtt

class I2CPin:

    def __init__(self, i2cDevice, register, number, path):
        self.i2cDevice = i2cDevice
        self.register = register
        self.number = number
        self.path = path
        self.i2cWriteController = i2c.I2CWriteController(i2cDevice, register, number)
        self.mqttController = mqtt.MQTTController(path, self.i2cWriteController)

    def set_enabled(self):
        self.i2cWriteController.set_enabled()
        self.mqttController.publish("ON")

    def set_disabled(self):
        self.i2cWriteController.set_disabled()
        self.mqttController.publish("OFF")

    def trigger_value(self):
        result = self.i2cWriteController.trigger_value()
        if  result == False:
            self.mqttController.publish("ON")
        else:
            self.mqttController.publish("OFF")

    def get_type():
        return self.type

    def get_number():
        return self.number

    def get_register():
        return self.number
