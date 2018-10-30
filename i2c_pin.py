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

        if pinType == Type.OUTPUT:
            self.set_mqtt_listener()

    def set_mqtt_listener(self):
        self.mqttController = mqtt.MQTTController(self.path,
                                i2c.I2CWriteController(self.register, self.number))

    def get_pin_type():
        return self.type

    def get_pin_number():
        return self.number

    def get_pin_register():
        return self.number
