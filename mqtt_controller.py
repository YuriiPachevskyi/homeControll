import time
import paho.mqtt.client as paho

class MQTTController:

    def __init__(self, brokerAdress, path, callback):
        self.callback = callback
        self.brokerAdress = brokerAdress
        self.path = path
        self.client=paho.Client(path)
        self.client.on_message=self.on_message
        self.client.connect(brokerAdress)
        self.client.loop_start()
        self.client.subscribe(path)

    def on_message(self, client, userdata, message):
        result = str(message.payload.decode("utf-8"))
        self.callback(result)
        self.client.publish(self.path + "/status", result)
