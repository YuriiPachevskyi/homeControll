import time
import i2c_pin
import i2c_controller as i2c
import mqtt_controller as mqtt

class I2COutManager:
    mqtt_controllers_list = {}
    def __init__(self, register):
        self.register = register

    def activate_out_pin(self, number, path):
        self.mqtt_controllers_list[path] = i2c_pin.I2CPin(i2c_pin.Type.OUTPUT, self.register, number, path)
        
manager = I2COutManager(0x20)
manager.activate_out_pin(0, "home/bedroom/switch1")
manager.activate_out_pin(1, "home/bedroom/switch2")
manager.activate_out_pin(2, "home/bedroom/switch3")
manager.activate_out_pin(3, "home/bedroom/switch4")
manager.activate_out_pin(4, "home/bedroom/switch5")
manager.activate_out_pin(5, "home/bedroom/switch6")
manager.activate_out_pin(6, "home/bedroom/switch7")
manager.activate_out_pin(7, "home/bedroom/switch8")
#I2CReadController(0x21).i2c_read()

while not 0: time.sleep(0.1)
