import paho.mqtt.client as mqtt
import settings
import logging

logger = logging.getLogger(__name__)

class MQTTController:
    def __init__(self, path, callback):
        self.callback = callback
        self.path = path

        try:
            # Attempt to use the new API versioning for paho-mqtt 2.0+
            from paho.mqtt.enums import CallbackAPIVersion
            self.client = mqtt.Client(CallbackAPIVersion.VERSION1, client_id=path)
        except ImportError:
            # Fallback for paho-mqtt < 2.0.0 which does not support/require callback_api_version
            self.client = mqtt.Client(client_id=path)

        self.client.on_message = self.on_message
        self.client.connect(settings.serverAddress)
        self.client.loop_start()
        self.client.subscribe(path)
        logger.info("MQTT subscribed to %s", path)

    def on_message(self, client, userdata, message):
        state = message.payload.decode("utf-8")
        swId = message.topic.split("/")[-1]
        self.callback(swId, state)

    def publish(self, id, state):
        # Use status path from settings instead of hardcoding
        base_path = settings.mqttStatusPath.replace('#', '')
        topic = f"{base_path}{id}"
        self.client.publish(topic, state)
        logger.info("MQTT published %s -> %s", topic, state)

    def stop(self):
        self.client.loop_stop()
        self.client.disconnect()
