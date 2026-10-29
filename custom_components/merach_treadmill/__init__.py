"""Merach-Laufband über das FitShow-Protokoll."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS, Platform
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .device import MerachTreadmill

PLATFORMS = [Platform.BINARY_SENSOR, Platform.BUTTON, Platform.NUMBER, Platform.SENSOR]

MerachConfigEntry = ConfigEntry[MerachTreadmill]


async def async_setup_entry(hass: HomeAssistant, entry: MerachConfigEntry) -> bool:
    """Eintrag einrichten."""
    device = MerachTreadmill(hass, entry.data[CONF_ADDRESS], entry.title)
    entry.runtime_data = device

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_create_background_task(
        hass, device.async_run(), f"{DOMAIN}_{entry.entry_id}"
    )
    entry.async_on_unload(device.async_disconnect)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: MerachConfigEntry) -> bool:
    """Eintrag entladen."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
