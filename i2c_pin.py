from enum import Enum
import i2c_controller as i2c
import mqtt_controller as mqtt

class Type(Enum):
    INPUT = 0
    OUTPUT = 1

class I2CPin:

    def __init__(self, pinType, register, number, path):
        self.type = pinType
        self.register = register
        self.number = number
        self.path = path
        self.i2cWriteController = i2c.I2CWriteController(self.register, self.number)

        if pinType == Type.OUTPUT:
            self.set_mqtt_listener()

    def set_mqtt_listener(self):
        self.mqttController = mqtt.MQTTController(self.path, self.i2cWriteController)

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
