"""Start/Stopp-Buttons."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import MerachConfigEntry
from .entity import MerachEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MerachConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    device = entry.runtime_data
    async_add_entities([StartButton(device, "start", "Start"), StopButton(device, "stop", "Stopp")])


class StartButton(MerachEntity, ButtonEntity):
    _attr_icon = "mdi:play"

    async def async_press(self) -> None:
        await self._device.async_start()


class StopButton(MerachEntity, ButtonEntity):
    _attr_icon = "mdi:stop"

    async def async_press(self) -> None:
        await self._device.async_stop()
