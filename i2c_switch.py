import time
import i2c_controller
import mqtt_controller

class I2CSwitchManager:
    def __init__(self):
        self.i2cController  = I2CPinController(0x20, 128)
        self.mqttController = MQTTController("10.42.0.2", "home/bedroom/switch1", self.mqtt_callback)
    
    def mqtt_callback(self, result):
        if result == "ON":
            self.i2cController.set_i2c_enabled()
        elif result == "OFF":
            self.i2cController.set_i2c_disabled()

        
I2CSwitchManager()
I2CReadController(0x21).i2c_read()

#bedroomSwitch = I2CPinController("10.42.0.2", "home/bedroom/switch1/set", 0x20, 255)

while not 0: time.sleep(0.1)
