"""Verbindung, FitShow-Steuerung und FTMS-Messwerte für das Merach-Laufband."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
import logging
import time

from bleak import BleakClient
from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.exc import BleakError
from bleak_retry_connector import BleakClientWithServiceCache, establish_connection

from homeassistant.components import bluetooth
from homeassistant.components.bluetooth import (
    BluetoothCallbackMatcher,
    BluetoothChange,
    BluetoothScanningMode,
    BluetoothServiceInfoBleak,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError

from .const import (
    KEEPALIVE_DATA,
    KEEPALIVE_INTERVAL,
    KEEPALIVE_UUID,
    MAX_SPEED,
    MIN_SPEED,
    NOTIFY_UUID,
    POLL_INTERVAL,
    RECONNECT_INTERVAL,
    STATUS_COUNTDOWN,
    STATUS_RUNNING,
    TREADMILL_DATA_UUID,
    WRITE_UUID,
)
from .ftms import parse_treadmill_data

_LOGGER = logging.getLogger(__name__)


def frame(*payload: int) -> bytes:
    """FitShow-Frame bauen: 02 <payload> <xor> 03."""
    checksum = 0
    for byte in payload:
        checksum ^= byte
    return bytes([0x02, *payload, checksum, 0x03])


CMD_STATUS = frame(0x51)
CMD_INFO_MODEL = frame(0x50, 0x00)
CMD_INFO_SPEED = frame(0x50, 0x03)
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
        self._advertised = asyncio.Event()
        self._keepalive_ok = False
        self._ftms_active = False
        # Das Laufband meldet Zeit und Distanz nicht, daher selbst mitzählen
        self._session_elapsed = 0.0
        self._session_distance = 0.0
        self._last_tick: float | None = None
        self._generation = 0

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

    @callback
    def _on_advertisement(
        self, _service_info: BluetoothServiceInfoBleak, _change: BluetoothChange
    ) -> None:
        self._advertised.set()

    async def async_run(self) -> None:
        """Verbinden, abfragen und bei Abbruch neu verbinden."""
        last_error: str | None = None
        unregister = bluetooth.async_register_callback(
            self.hass,
            self._on_advertisement,
            BluetoothCallbackMatcher(address=self.address, connectable=True),
            BluetoothScanningMode.ACTIVE,
        )
        first_attempt = True
        ended_at = time.monotonic()
        try:
            while True:
                if not first_attempt:
                    await asyncio.sleep(RECONNECT_INTERVAL)
                    # Erst wieder verbinden, wenn das Laufband sich frisch meldet.
                    # Blinde Versuche pausieren beim Pi-Adapter das Scannen.
                    _LOGGER.debug("%s: warte auf Advertisement", self.name)
                    await self._wait_for_advertisement(ended_at)
                    _LOGGER.debug("%s: Laufband meldet sich wieder", self.name)
                first_attempt = False
                try:
                    await self._connect()
                    last_error = None
                    loop = asyncio.get_running_loop()
                    next_keepalive = loop.time() + KEEPALIVE_INTERVAL
                    while self._client is not None and self._client.is_connected:
                        if loop.time() >= next_keepalive:
                            await self._keepalive()
                            next_keepalive = loop.time() + KEEPALIVE_INTERVAL
                        await self._write(CMD_STATUS)
                        await asyncio.sleep(POLL_INTERVAL)
                    _LOGGER.warning("%s: Verbindung verloren", self.name)
                except (BleakError, TimeoutError) as err:
                    error = f"{type(err).__name__}: {err}"
                    # Gleiche Fehler nur einmal als Warnung, Wiederholungen im Debug-Log
                    log = _LOGGER.debug if error == last_error else _LOGGER.warning
                    log("%s: Verbindung fehlgeschlagen: %s", self.name, error)
                    last_error = error
                except Exception:
                    _LOGGER.exception("%s: Unerwarteter Fehler", self.name)
                await self.async_disconnect()
                ended_at = time.monotonic()
        finally:
            unregister()
            await self.async_disconnect()

    async def _wait_for_advertisement(self, since: float) -> None:
        """Warten, bis das Laufband nach `since` wieder gesehen wurde.

        Home Assistant meldet unveränderte Advertisements nicht erneut per
        Callback, nach dem Aus- und Einschalten sendet das Laufband aber exakt
        dasselbe. Daher zusätzlich den Zeitstempel der letzten Sichtung prüfen.
        """
        self._advertised.clear()
        while True:
            info = bluetooth.async_last_service_info(
                self.hass, self.address, connectable=True
            )
            if info is not None and info.time > since:
                return
            try:
                await asyncio.wait_for(self._advertised.wait(), timeout=5)
                return
            except TimeoutError:
                pass

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
        self._generation += 1
        # Ablauf wie die Merach-App: erst Keep-alive, dann Notifications, dann Geräteinfos
        await self._setup_keepalive(client)

        if client.services.get_characteristic(NOTIFY_UUID) is None:
            # Unvollständiger GATT-Cache, beim nächsten Versuch neu einlesen
            await client.clear_cache()
            raise BleakError("FitShow-Characteristic FFF1 nicht gefunden, Cache geleert")
        _LOGGER.debug("%s: Verbindung steht, aktiviere Notifications", self.name)
        await client.start_notify(NOTIFY_UUID, self._bind(self._on_notify))

        self._ftms_active = False
        try:
            await client.start_notify(
                TREADMILL_DATA_UUID, self._bind(self._on_treadmill_data)
            )
            self._ftms_active = True
        except BleakError as err:
            _LOGGER.warning(
                "%s: FTMS-Daten nicht verfügbar, nutze nur FitShow: %s", self.name, err
            )

        for command in (CMD_INFO_MODEL, CMD_INFO_SPEED):
            try:
                await self._write(command)
            except BleakError as err:
                _LOGGER.debug("%s: Geräteinfo-Abfrage fehlgeschlagen: %s", self.name, err)
        _LOGGER.info("%s: verbunden", self.name)
        self.state.connected = True
        self._notify_listeners()

    async def async_disconnect(self) -> None:
        """Verbindung trennen."""
        client, self._client = self._client, None
        if client is not None and client.is_connected:
            try:
                await client.disconnect()
            except (BleakError, TimeoutError) as err:
                # Z. B. Laufband ohne Strom: Trennen läuft ins Leere, darf aber
                # die Wiederverbindungs-Schleife nicht beenden
                _LOGGER.debug("%s: Trennen fehlgeschlagen: %s", self.name, err)
        self._set_disconnected()

    def _on_disconnect(self, _client: BleakClient) -> None:
        _LOGGER.debug("%s: getrennt", self.name)
        self.hass.loop.call_soon_threadsafe(self._set_disconnected)

    @callback
    def _set_disconnected(self) -> None:
        self._last_tick = None
        if not self.state.connected:
            return
        self.state = TreadmillState()
        self._notify_listeners()

    def _tick(self) -> None:
        """Trainingszeit und Distanz seit der letzten Meldung fortschreiben."""
        now = time.monotonic()
        state = self.state
        if self._last_tick is not None and state.status == STATUS_RUNNING:
            dt = min(now - self._last_tick, 30.0)
            self._session_elapsed += dt
            self._session_distance += state.speed / 3.6 * dt
        self._last_tick = now
        state.elapsed = round(self._session_elapsed)
        state.distance = round(self._session_distance)

    def _bind(
        self, handler: Callable[[BleakGATTCharacteristic, bytearray], None]
    ) -> Callable[[BleakGATTCharacteristic, bytearray], None]:
        """Callback an die aktuelle Verbindung binden.

        Nach einem unsauberen Abbruch liefert der ESPHome-Proxy Notifications
        teils noch an die Abos alter Verbindungen. Die werden so ignoriert.
        """
        generation = self._generation

        def wrapper(char: BleakGATTCharacteristic, data: bytearray) -> None:
            if generation == self._generation:
                handler(char, data)

        return wrapper

    def _on_notify(self, _char: BleakGATTCharacteristic, data: bytearray) -> None:
        _LOGGER.debug("%s: RX %s", self.name, data.hex())
        if len(data) < 5 or data[0] != 0x02 or data[1] != 0x51:
            return

        state = self.state
        self._tick()
        previous = state.status
        state.status = data[2]
        if state.status == STATUS_COUNTDOWN and previous != STATUS_COUNTDOWN:
            # Neues Training
            self._session_elapsed = 0.0
            self._session_distance = 0.0
            self._tick()
        if state.status == STATUS_RUNNING:
            # FTMS meldet die Geschwindigkeit zuverlässiger, FitShow nur als Ersatz
            if not self._ftms_active:
                state.speed = data[3] / 10
        else:
            state.speed = 0.0
        self.hass.loop.call_soon_threadsafe(self._notify_listeners)

    def _on_treadmill_data(self, _char: BleakGATTCharacteristic, data: bytearray) -> None:
        _LOGGER.debug("%s: FTMS %s", self.name, data.hex())
        parsed = parse_treadmill_data(bytes(data))
        state = self.state
        self._tick()
        if parsed.speed is not None and state.status == STATUS_RUNNING:
            state.speed = parsed.speed
        self.hass.loop.call_soon_threadsafe(self._notify_listeners)

    async def _write(self, data: bytes, uuid: str = WRITE_UUID) -> None:
        async with self._write_lock:
            client = self._client
            if client is None or not client.is_connected:
                raise BleakError("nicht verbunden")
            await client.write_gatt_char(uuid, data, response=True)

    async def _setup_keepalive(self, client: BleakClient) -> None:
        """Keep-alive vorbereiten. Fehler hier sollen die Verbindung nicht kosten."""
        self._keepalive_ok = False
        if client.services.get_characteristic(KEEPALIVE_UUID) is None:
            _LOGGER.warning(
                "%s: Keep-alive-Characteristic nicht gefunden, fahre ohne fort", self.name
            )
            await client.clear_cache()
            return
        try:
            # Die App bekommt den Wert als Indication zurück, also vorher abonnieren
            await client.start_notify(
                KEEPALIVE_UUID, self._bind(self._on_keepalive_indication)
            )
        except BleakError as err:
            _LOGGER.debug("%s: Keep-alive-Indications nicht aktivierbar: %s", self.name, err)
        self._keepalive_ok = True
        await self._keepalive()

    def _on_keepalive_indication(
        self, _char: BleakGATTCharacteristic, data: bytearray
    ) -> None:
        _LOGGER.debug("%s: Keep-alive-Antwort %s", self.name, data.hex())

    async def _keepalive(self) -> None:
        if not self._keepalive_ok:
            return
        _LOGGER.debug("%s: Keep-alive", self.name)
        try:
            await self._write(KEEPALIVE_DATA, KEEPALIVE_UUID)
        except BleakError as err:
            if self._client is None or not self._client.is_connected:
                raise
            _LOGGER.warning(
                "%s: Keep-alive abgelehnt (%s), fahre ohne fort", self.name, err
            )
            self._keepalive_ok = False

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
