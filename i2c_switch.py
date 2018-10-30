import time
import i2c_pin
import i2c_controller as i2c
import mqtt_controller as mqtt

server_address = "10.42.0.2"

class I2COutManager:
    mqtt_controllers_list = {}
    def __init__(self, register):
        self.register = register

    def activate_out_pin(self, pin, path):
        self.mqtt_controllers_list[path] = mqtt.MQTTController(server_address, path, i2c.I2CPinController(self.register, pin))
        
manager = I2COutManager(0x20)
manager.activate_out_pin(0, "home/bedroom/switch1")
manager.activate_out_pin(1, "home/bedroom/switch2")
manager.activate_out_pin(2, "home/bedroom/switch3")
manager.activate_out_pin(3, "home/bedroom/switch4")
#I2COutManager(0x20, 4, "home/bedroom/switch5")
#I2COutManager(0x20, 5, "home/bedroom/switch6")
#I2COutManager(0x20, 6, "home/bedroom/switch7")
#I2COutManager(0x20, 7, "home/bedroom/switch8")
#I2CReadController(0x21).i2c_read()

#bedroomSwitch = I2CPinController("10.42.0.2", "home/bedroom/switch1/set", 0x20, 255)

while not 0: time.sleep(0.1)
