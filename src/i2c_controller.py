import smbus2
import time
import logging
import settings
from models import I2CInputDevice

logger = logging.getLogger(__name__)

class I2CController:
    _shared_buses = {}

    def _get_bus(self, bus_idx):
        if bus_idx not in I2CController._shared_buses:
            try:
                I2CController._shared_buses[bus_idx] = smbus2.SMBus(bus_idx)
                logger.info("Opened I2C bus %s", bus_idx)
            except Exception as e:
                logger.error("Could not open I2C bus %s: %s", bus_idx, e)
                return None
        return I2CController._shared_buses[bus_idx]

    def _parse_id(self, input_id):
        device = int(input_id[0])
        register = int(input_id[1:-1])
        pin = int(input_id[-1])
        return device, register, pin

class I2CWriteController(I2CController):
    def __init__(self):
        super().__init__()

    def set_enabled(self, i2cDevice, register, pin):
        bus = self._get_bus(i2cDevice)
        if not bus: return
        value = bus.read_byte(register) & ~(1 << pin)
        bus.write_byte(register, value)
        logger.info("Set ENABLED: device=%s register=%s pin=%s", i2cDevice, register, pin)

    def set_disabled(self, i2cDevice, register, pin):
        bus = self._get_bus(i2cDevice)
        if not bus: return
        value = bus.read_byte(register) | (1 << pin)
        bus.write_byte(register, value)
        logger.info("Set DISABLED: device=%s register=%s pin=%s", i2cDevice, register, pin)

    def trigger_value(self, i2cDevice, register, pin):
        bus = self._get_bus(i2cDevice)
        if not bus: return False
        value = bus.read_byte(register) ^ (1 << pin)
        bus.write_byte(register, value)
        result = bool(value & (1 << pin))
        logger.info("Triggered: device=%s register=%s pin=%s -> %s", i2cDevice, register, pin, result)
        return result

class I2CReadController(I2CController):
    def __init__(self, inputsDict, callback):
        super().__init__()
        self.callback = callback
        self.inputDict = {}
        self.expanderState = {}
        self._write_ctrl = I2CWriteController()
        self.init_inputs(inputsDict)

    def init_inputs(self, inputsDict):
        for key in inputsDict:
            device, register, pin = self._parse_id(key)
            reg_key = f"{device}:{register}"
            self.inputDict[reg_key] = self.inputDict.get(reg_key, 0) | (1 << pin)

    def clear_input_state(self, input_id):
        device, register, pin = self._parse_id(input_id)
        logger.info("Clear input state: %s", input_id)
        self._write_ctrl.set_disabled(device, register, pin)

    def is_input_state_changed(self, mask, value):
        return (value & mask) ^ mask

    def try_to_notify(self, targetKey):
        keyForNotify = None
        for key in list(self.expanderState.keys()):
            if key.startswith(targetKey + ":"):
                keyForNotify = key
        if keyForNotify:
            self.callback(keyForNotify, self.expanderState[keyForNotify])
            self.expanderState.pop(keyForNotify, None)

    def i2c_read(self):
        while True:
            for key in self.inputDict:
                parts = key.split(":")
                i2cDevice = int(parts[0])
                i2cRegister = int(parts[1])
                try:
                    bus = self._get_bus(i2cDevice)
                    if not bus: continue
                    pinsState = bus.read_byte(i2cRegister)
                except OSError as e:
                    logger.error("I2C Error on bus %s, reg %s: %s", i2cDevice, i2cRegister, e)
                    continue
                modifiedPins = self.is_input_state_changed(self.inputDict[key], pinsState)

                if not modifiedPins:
                    if self.expanderState:
                        self.try_to_notify(key)
                else:
                    exStKey = f"{key}:{modifiedPins}"
                    self.expanderState[exStKey] = self.expanderState.get(exStKey, 0) + 1
            time.sleep(settings.i2cReadTimeout)
