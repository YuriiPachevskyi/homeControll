import sys
import time
import json
import settings
import paho.mqtt.client as paho

class MQTTController:

    def __init__(self):
        self.client=paho.Client("/home/#")
        self.client.connect(settings.serverAddress)

    def publish(self, suffix):
        jsonFile = open("/home/yuso/work/controllService/conf.json", "r")
        data = json.load(jsonFile)
        jsonFile.close()

        for i in range(len(data["switch"])):
            path = data["switch"][i]["path"] + suffix
            state = data["switch"][i]["state"]
            print("publish state", path, "state", state)
            self.client.publish(path, state)
            time.sleep(0.05)

for parameter in sys.argv[1:]:
    MQTTController().publish(parameter)
