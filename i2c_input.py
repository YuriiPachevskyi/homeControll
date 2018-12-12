class I2CInputDevice:
    def __init__(self, onShort, onLong, onLongL):
        self.onShort = onShort
        self.onLong = onLong
        self.onLongL = onLongL

    def get_on_short_id(self):
        return self.onShort

    def get_on_long_id(self):
        return self.onLong

    def get_on_longl_id(self):
        return self.onLongL

