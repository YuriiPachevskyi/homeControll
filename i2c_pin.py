from enum import Enum

class Type(Enum):
    INPUT = 0
    OUTPUT = 1

class I2CPin:

    def __init__(self, pin_type, number):
        self.type = pin_type
        self.number = register

