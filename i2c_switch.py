import time
import i2c_controller as i2c
import mqtt_controller as mqtt

class I2COutManager:
    def __init__(self, register, pin, address, path):
        self.register = register
        self.address = address
        self.i2cController  = i2c.I2CPinController(register, pin)
        self.mqttController = mqtt.MQTTController(address, path, self.mqtt_callback)

#    def activate_pin(self, pin_type, pin_number, path)
    
    def mqtt_callback(self, result):
        print("mqtt_controller result = ", result)
        if result == "ON":
            self.i2cController.set_i2c_enabled()
        elif result == "OFF":
            self.i2cController.set_i2c_disabled()

        
I2COutManager(0x20, 0, "10.42.0.2", "home/bedroom/switch1")
I2COutManager(0x20, 1, "10.42.0.2", "home/bedroom/switch2")
I2COutManager(0x20, 2, "10.42.0.2", "home/bedroom/switch3")
I2COutManager(0x20, 3, "10.42.0.2", "home/bedroom/switch4")
I2COutManager(0x20, 4, "10.42.0.2", "home/bedroom/switch5")
I2COutManager(0x20, 5, "10.42.0.2", "home/bedroom/switch6")
I2COutManager(0x20, 6, "10.42.0.2", "home/bedroom/switch7")
I2COutManager(0x20, 7, "10.42.0.2", "home/bedroom/switch8")
#I2CReadController(0x21).i2c_read()

#bedroomSwitch = I2CPinController("10.42.0.2", "home/bedroom/switch1/set", 0x20, 255)

while not 0: time.sleep(0.1)
