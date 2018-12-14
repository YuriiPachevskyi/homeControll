import json

class StateController:

    def find_id(self, data, elementId):
        for i in range(len(data["switch"])):
            if data["switch"][i]["id"] == elementId:
                return i

    def save_state(self, i2cDevice, register, pin, state):
        jsonFile = open("/home/yuso/work/controllService/conf.json", "r")
        data = json.load(jsonFile)
        jsonFile.close()

        ## Working with buffered content
        elementId = str(i2cDevice) + str(register) + str(pin)
        data["switch"][self.find_id(data, elementId)]["state"] = state

         # Save our changes to JSON file
        jsonFile = open("/home/yuso/work/controllService/conf.json", "w+")
        jsonFile.write(json.dumps(data, sort_keys=True, indent=4))
        jsonFile.close()

