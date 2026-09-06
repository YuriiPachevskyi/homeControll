"""Shared I2C bus access for PCF8574-style 8-bit I/O expanders.

Mirrors the bit logic of the original standalone script
(homeControll/src/i2c_controller.py): a relay output is ACTIVE-LOW —
clearing a bit enables (turns ON) the relay, setting a bit disables
(turns OFF) the relay. IDs are "[bus][i2c_addr][pin]" strings, e.g.
"1566" = I2C bus 1, address 56 (0x38), pin 6.
"""
import logging
import threading

import smbus2

_LOGGER = logging.getLogger(__name__)


def parse_id(entity_id: str):
    try:
        bus = int(entity_id[0])
        addr = int(entity_id[1:-1])
        pin = int(entity_id[-1])
        return bus, addr, pin
    except (ValueError, IndexError):
        _LOGGER.error(
            "Invalid id %s, expected [bus][i2c_addr][pin]", entity_id
        )
        return None, None, None


class I2CBusManager:
    """One shared, lock-guarded SMBus handle per bus index."""

    _buses: dict[int, smbus2.SMBus] = {}
    _lock = threading.Lock()
    # Tracks which (bus) / (bus, addr) are currently failing, so errors are
    # logged once on failure and once on recovery instead of every poll.
    _bus_open_failed: set[int] = set()
    _addr_failed: set[tuple[int, int]] = set()

    @classmethod
    def _get_bus(cls, bus_idx: int):
        with cls._lock:
            if bus_idx not in cls._buses:
                try:
                    cls._buses[bus_idx] = smbus2.SMBus(bus_idx)
                    _LOGGER.info("Opened I2C bus %s", bus_idx)
                    cls._bus_open_failed.discard(bus_idx)
                except Exception as err:  # noqa: BLE001 - hardware access, keep broad
                    if bus_idx not in cls._bus_open_failed:
                        _LOGGER.error("Could not open I2C bus %s: %s", bus_idx, err)
                        cls._bus_open_failed.add(bus_idx)
                    return None
            return cls._buses[bus_idx]

    @classmethod
    def is_pin_on(cls, bus_idx: int, addr: int, pin: int) -> bool | None:
        bus = cls._get_bus(bus_idx)
        if bus is None:
            return None
        addr_key = (bus_idx, addr)
        with cls._lock:
            try:
                value = bus.read_byte(addr)
            except OSError as err:
                if addr_key not in cls._addr_failed:
                    _LOGGER.error(
                        "I2C read error bus=%s addr=%s (device not responding - check "
                        "wiring/address, e.g. `i2cdetect -y %s` on the host): %s",
                        bus_idx, addr, bus_idx, err,
                    )
                    cls._addr_failed.add(addr_key)
                return None
        if addr_key in cls._addr_failed:
            _LOGGER.info("I2C read recovered bus=%s addr=%s", bus_idx, addr)
            cls._addr_failed.discard(addr_key)
        return not bool(value & (1 << pin))

    @classmethod
    def set_pin(cls, bus_idx: int, addr: int, pin: int, on: bool) -> bool:
        bus = cls._get_bus(bus_idx)
        if bus is None:
            return False
        addr_key = (bus_idx, addr)
        with cls._lock:
            try:
                value = bus.read_byte(addr)
                value = value & ~(1 << pin) if on else value | (1 << pin)
                bus.write_byte(addr, value)
                current = bus.read_byte(addr)
            except OSError as err:
                if addr_key not in cls._addr_failed:
                    _LOGGER.error(
                        "I2C write error bus=%s addr=%s pin=%s (device not responding - "
                        "check wiring/address, e.g. `i2cdetect -y %s` on the host): %s",
                        bus_idx, addr, pin, bus_idx, err,
                    )
                    cls._addr_failed.add(addr_key)
                return False
        if addr_key in cls._addr_failed:
            _LOGGER.info("I2C write recovered bus=%s addr=%s", bus_idx, addr)
            cls._addr_failed.discard(addr_key)
        _LOGGER.info(
            "Set %s: bus=%s addr=%s pin=%s (%s)",
            "ENABLED" if on else "DISABLED",
            bus_idx,
            addr,
            pin,
            bin(current)[2:].zfill(8),
        )
        return True
