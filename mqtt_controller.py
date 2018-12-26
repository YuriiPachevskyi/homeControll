import time
import settings
import i2c_controller as i2c
import paho.mqtt.client as paho

class MQTTController:

    def __init__(self, path, callback):
        self.callback = callback
        self.path = path
        self.client=paho.Client(path)
        self.client.on_message=self.on_message
        self.client.connect(settings.serverAddress)
        self.client.loop_start()
        self.client.subscribe(path)

    def on_message(self, client, userdata, message):
        state = str(message.payload.decode("utf-8"))
        swId = message.topic[-4:]
        self.callback(swId, state)
        self.publish(swId, state)

    def publish(self, id, state):
        self.client.publish("home/status/main/" + id, state)

