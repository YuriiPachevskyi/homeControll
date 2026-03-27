class I2CInputDevice:
    def __init__(self, onShort, onLong, onLongL):
        self.onShort = onShort
        self.onLong = onLong
        self.onLongL = onLongL

    def onShortId(self):
        return self.onShort

    def onLongId(self):
        return self.onLong

    def onLonglId(self):
        return self.onLongL

