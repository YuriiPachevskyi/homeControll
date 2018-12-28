from subprocess import call
import paho.mqtt.client
import settings
import threading
import time

class UiStateUpdateThread(threading.Thread):
    def __init__(self, path, switchDict, mqttController):
        super(UiStateUpdateThread, self).__init__()
        self.mqttController = mqttController
        self.switchDict = switchDict
        self.path = path
        self.client=paho.mqtt.client.Client(path + "2")
        self.client.on_message=self.on_message
        self.client.connect(settings.serverAddress)
        self.client.loop_start()
        self.client.subscribe(path)

    def on_message(self, client, userdata, message):
        state = str(message.payload.decode("utf-8"))
        swId = message.topic[-4:]
        if self.switchDict.has_key(swId):
            self.switchDict[swId] = state

    def run(self):
        result = None

        while result != 0 :
            result = call(["curl", "-I", settings.serverAddressAndPort])
            time.sleep(3)
        for key in self.switchDict:
            self.mqttController.publish(key, self.switchDict[key])

class FileStateBackupThread(threading.Thread):
    switchDictPrev = {}
    def __init__(self, path, switchDict):
        super(FileStateBackupThread, self).__init__()
        self.switchDict = switchDict
        self.init_prev_dict()
        self.path = path
        self.client=paho.mqtt.client.Client(path)
        self.client.on_message=self.on_message
        self.client.connect(settings.serverAddress)
        self.client.loop_start()
        self.client.subscribe(path)

    def init_prev_dict(self):
        for key in self.switchDict:
            self.switchDictPrev[key] = self.switchDict[key]

    def on_message(self, client, userdata, message):
        state = str(message.payload.decode("utf-8"))
        swId = message.topic[-4:]
        if self.switchDict.has_key(swId):
            self.switchDict[swId] = state

    def saveSwitchState(self, id, state):
        stateChange = "s/state_" + id + ":.*/state_" + id + ": \"" + state + "\"/g"
        call(["sed", "-i", stateChange, settings.confSwitchesFile])

    def run(self):
        while True :
            for key in self.switchDict:
                if self.switchDict[key] != self.switchDictPrev[key]:
                    self.saveSwitchState(key, self.switchDict[key])
                    self.switchDictPrev[key] = self.switchDict[key]
            time.sleep(5)
