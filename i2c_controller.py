import smbus2
import time
import logging
import settings
from models import I2CInputDevice

logger = logging.getLogger(__name__)

class I2CController:
    def __init__(self):
        self.busArray = [None, smbus2.SMBus(1)]
        try:
            smbus2.SMBus(1).read_byte(0x38)
        except Exception as e:
            logger.warning("I2C bus init failed: %s", e)

class I2CWriteController(I2CController):
    def __init__(self):
        super().__init__()

    def set_enabled(self, i2cDevice, register, pin):
        value = self.busArray[i2cDevice].read_byte(register) & ~(1 << pin)
        self.busArray[i2cDevice].write_byte(register, value)
        logger.info("Set ENABLED: device=%s register=%s pin=%s", i2cDevice, register, pin)

    def set_disabled(self, i2cDevice, register, pin):
        value = self.busArray[i2cDevice].read_byte(register) | (1 << pin)
        self.busArray[i2cDevice].write_byte(register, value)
        logger.info("Set DISABLED: device=%s register=%s pin=%s", i2cDevice, register, pin)

    def trigger_value(self, i2cDevice, register, pin):
        value = self.busArray[i2cDevice].read_byte(register) ^ (1 << pin)
        self.busArray[i2cDevice].write_byte(register, value)
        result = bool(value & (1 << pin))
        logger.info("Triggered: device=%s register=%s pin=%s -> %s", i2cDevice, register, pin, result)
        return result

class I2CReadController(I2CController):
    def __init__(self, inputsDict, callback):
        super().__init__()
        self.callback = callback
        self.inputDict = {}
        self.expanderState = {}
        self.init_inputs(inputsDict)

    def init_inputs(self, inputsDict):
        for key in inputsDict:
            devRegKey = key[:-1]
            devRegPin = int(key[-1:])
            self.inputDict[devRegKey] = self.inputDict.get(devRegKey, 0) | (1 << devRegPin)

    def clear_input_state(self, input_id):
        i2cDevice = int(input_id[:1])
        i2cRegister = int(input_id[1:-1])
        i2cPin = int(input_id[-1:])
        logger.info("Clear input state: %s", input_id)
        I2CWriteController.set_disabled(self, i2cDevice, i2cRegister, i2cPin)

    def is_input_state_changed(self, mask, value):
        return (value & mask) ^ mask

    def try_to_notify(self, targetKey):
        keyForNotify = None
        for key in self.expanderState:
            if key[:3] == targetKey:
                keyForNotify = key
        if keyForNotify:
            self.callback(keyForNotify, self.expanderState[keyForNotify])
            self.expanderState.pop(keyForNotify, None)

    def i2c_read(self):
        while True:
            for key in self.inputDict:
                i2cDevice = int(key[:-2])
                i2cRegister = int(key[1:])
                try:
                    pinsState = self.busArray[i2cDevice].read_byte(i2cRegister)
                except:
                    logger.warning("Failed to read i2cRegister %s", i2cRegister)
                    continue
                modifiedPins = self.is_input_state_changed(self.inputDict[key], pinsState)

                if not modifiedPins:
                    if self.expanderState:
                        self.try_to_notify(key)
                else:
                    exStKey = key + str(modifiedPins)
                    self.expanderState[exStKey] = self.expanderState.get(exStKey, 0) + 1
            time.sleep(settings.i2cReadTimeout)


