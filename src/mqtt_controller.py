import paho.mqtt.client as mqtt
import settings
import logging

logger = logging.getLogger(__name__)

class MQTTController:
    def __init__(self, path, callback):
        self.callback = callback
        self.path = path
        self.client = mqtt.Client(client_id=path, callback_api_version=1)
        self.client.on_message = self.on_message
        self.client.connect(settings.serverAddress)
        self.client.loop_start()
        self.client.subscribe(path)
        logger.info("MQTT subscribed to %s", path)

    def on_message(self, client, userdata, message):
        state = message.payload.decode("utf-8")
        swId = message.topic[-4:]
        self.callback(swId, state)

    def publish(self, id, state):
        topic = f"home/status/main/{id}"
        self.client.publish(topic, state)
        logger.info("MQTT published %s -> %s", topic, state)
