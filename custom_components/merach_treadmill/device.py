"""Verbindung und FitShow-Protokoll für das Merach-Laufband."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
import logging

from bleak import BleakClient
from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.exc import BleakError
from bleak_retry_connector import BleakClientWithServiceCache, establish_connection

from homeassistant.components import bluetooth
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError

from .const import (
    MAX_SPEED,
    MIN_SPEED,
    NOTIFY_UUID,
    POLL_INTERVAL,
    RECONNECT_INTERVAL,
    STATUS_RUNNING,
    WRITE_UUID,
)

_LOGGER = logging.getLogger(__name__)


def frame(*payload: int) -> bytes:
    """FitShow-Frame bauen: 02 <payload> <xor> 03."""
    checksum = 0
    for byte in payload:
        checksum ^= byte
    return bytes([0x02, *payload, checksum, 0x03])


CMD_STATUS = frame(0x51)
CMD_START = frame(0x53, 0x01, 0, 0, 0, 0, 0, 0, 0, 0)
CMD_STOP = frame(0x53, 0x03)


def cmd_speed(kmh: float) -> bytes:
    """Zielgeschwindigkeit in 0,1 km/h, Steigung 0."""
    return frame(0x53, 0x02, round(kmh * 10), 0x00)


@dataclass
class TreadmillState:
    """Zuletzt gemeldeter Zustand."""

    connected: bool = False
    status: int | None = None
    speed: float = 0.0
    elapsed: int | None = None
    distance: int | None = None
    calories: int | None = None
    steps: int | None = None


class MerachTreadmill:
    """Hält die BLE-Verbindung und fragt den Status zyklisch ab."""

    def __init__(self, hass: HomeAssistant, address: str, name: str) -> None:
        self.hass = hass
        self.address = address
        self.name = name
        self.state = TreadmillState()
        self._client: BleakClient | None = None
        self._listeners: list[Callable[[], None]] = []
        self._write_lock = asyncio.Lock()

    def add_listener(self, update_callback: Callable[[], None]) -> Callable[[], None]:
        """Callback für Zustandsänderungen registrieren."""
        self._listeners.append(update_callback)

        def remove() -> None:
            self._listeners.remove(update_callback)

        return remove

    @callback
    def _notify_listeners(self) -> None:
        for update_callback in list(self._listeners):
            update_callback()

    async def async_run(self) -> None:
        """Verbinden, abfragen und bei Abbruch neu verbinden."""
        last_error: str | None = None
        try:
            while True:
                try:
                    await self._connect()
                    last_error = None
                    while self._client is not None and self._client.is_connected:
                        await self._write(CMD_STATUS)
                        await asyncio.sleep(POLL_INTERVAL)
                except (BleakError, TimeoutError) as err:
                    error = f"{type(err).__name__}: {err}"
                    # Gleiche Fehler nur einmal als Warnung, Wiederholungen im Debug-Log
                    log = _LOGGER.debug if error == last_error else _LOGGER.warning
                    log("%s: Verbindung fehlgeschlagen: %s", self.name, error)
                    last_error = error
                except Exception:
                    _LOGGER.exception("%s: Unerwarteter Fehler", self.name)
                await self.async_disconnect()
                await asyncio.sleep(RECONNECT_INTERVAL)
        finally:
            await self.async_disconnect()

    async def _connect(self) -> None:
        ble_device = bluetooth.async_ble_device_from_address(
            self.hass, self.address, connectable=True
        )
        if ble_device is None:
            raise BleakError("Laufband nicht in Reichweite oder ausgeschaltet")

        _LOGGER.debug("%s: verbinde mit %s", self.name, ble_device)
        client = await establish_connection(
            BleakClientWithServiceCache,
            ble_device,
            self.name,
            disconnected_callback=self._on_disconnect,
            max_attempts=3,
        )
        self._client = client
        _LOGGER.debug("%s: Verbindung steht, aktiviere Notifications", self.name)
        await client.start_notify(NOTIFY_UUID, self._on_notify)
        _LOGGER.info("%s: verbunden", self.name)
        self.state.connected = True
        self._notify_listeners()

    async def async_disconnect(self) -> None:
        """Verbindung trennen."""
        client, self._client = self._client, None
        if client is not None and client.is_connected:
            try:
                await client.disconnect()
            except BleakError:
                pass
        self._set_disconnected()

    def _on_disconnect(self, _client: BleakClient) -> None:
        _LOGGER.debug("%s: getrennt", self.name)
        self.hass.loop.call_soon_threadsafe(self._set_disconnected)

    @callback
    def _set_disconnected(self) -> None:
        if not self.state.connected:
            return
        self.state = TreadmillState()
        self._notify_listeners()

    def _on_notify(self, _char: BleakGATTCharacteristic, data: bytearray) -> None:
        _LOGGER.debug("%s: RX %s", self.name, data.hex())
        if len(data) < 5 or data[0] != 0x02 or data[1] != 0x51:
            return

        state = self.state
        state.status = data[2]
        if state.status == STATUS_RUNNING and len(data) >= 15:
            state.speed = data[3] / 10
            state.elapsed = data[5] | data[6] << 8
            state.distance = data[7] | data[8] << 8
            state.calories = data[9] | data[10] << 8
            state.steps = data[11] | data[12] << 8
        elif state.status != STATUS_RUNNING:
            state.speed = 0.0
        self.hass.loop.call_soon_threadsafe(self._notify_listeners)

    async def _write(self, data: bytes) -> None:
        async with self._write_lock:
            client = self._client
            if client is None or not client.is_connected:
                raise BleakError("nicht verbunden")
            await client.write_gatt_char(WRITE_UUID, data, response=True)

    async def _command(self, data: bytes) -> None:
        try:
            await self._write(data)
        except (BleakError, TimeoutError) as err:
            raise HomeAssistantError(f"Laufband nicht erreichbar: {err}") from err

    async def async_start(self) -> None:
        """Band starten (mit Countdown)."""
        await self._command(CMD_START)

    async def async_stop(self) -> None:
        """Band stoppen."""
        await self._command(CMD_STOP)

    async def async_set_speed(self, kmh: float) -> None:
        """Zielgeschwindigkeit setzen."""
        kmh = min(max(kmh, MIN_SPEED), MAX_SPEED)
        await self._command(cmd_speed(kmh))
