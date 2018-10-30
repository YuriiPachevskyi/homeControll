import time
import i2c_controller as i2c
import paho.mqtt.client as paho

class MQTTController:

    def __init__(self, brokerAdress, path, i2cController):
        self.path = path
        self.client=paho.Client(path)
        self.client.on_message=self.on_message
        self.client.connect(brokerAdress)
        self.client.loop_start()
        self.client.subscribe(path)
        self.i2cController = i2cController

    def on_message(self, client, userdata, message):
        result = str(message.payload.decode("utf-8"))
        if result == "ON":
            self.i2cController.set_i2c_enabled()
        elif result == "OFF":
            self.i2cController.set_i2c_disabled()
        self.publish(result)

    def publish(self, message):
        self.client.publish(self.path + "/status", message)
