from typing import List

class I2CInputDevice:
    def __init__(self, onShort: List[str], onLong: List[str], onLongL: List[str]):
        self.onShort = onShort
        self.onLong = onLong
        self.onLongL = onLongL

    def onShortId(self) -> List[str]:
        return self.onShort

    def onLongId(self) -> List[str]:
        return self.onLong

    def onLonglId(self) -> List[str]:
        return self.onLongL
