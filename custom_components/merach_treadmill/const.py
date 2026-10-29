"""Konstanten für die Merach-Laufband-Integration."""

DOMAIN = "merach_treadmill"

SERVICE_UUID = "0000fff0-0000-1000-8000-00805f9b34fb"
NOTIFY_UUID = "0000fff1-0000-1000-8000-00805f9b34fb"
WRITE_UUID = "0000fff2-0000-1000-8000-00805f9b34fb"

POLL_INTERVAL = 1.0
RECONNECT_INTERVAL = 10.0

MIN_SPEED = 1.0
MAX_SPEED = 6.0

STATUS_NAMES = {
    0x00: "Bereit",
    0x01: "Beendet",
    0x02: "Countdown",
    0x03: "Läuft",
    0x04: "Stoppt",
    0x05: "Fehler",
    0x06: "Sicherheitsschlüssel",
    0x0A: "Pausiert",
}
STATUS_RUNNING = 0x03
