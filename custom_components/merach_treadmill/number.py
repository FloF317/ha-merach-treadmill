"""Zielgeschwindigkeit als Schieberegler."""

from __future__ import annotations

from homeassistant.components.number import NumberDeviceClass, NumberEntity, NumberMode
from homeassistant.const import UnitOfSpeed
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import MerachConfigEntry
from .const import MAX_SPEED, MIN_SPEED, STATUS_RUNNING
from .entity import MerachEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MerachConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    device = entry.runtime_data
    async_add_entities([SpeedNumber(device, "target_speed", "Zielgeschwindigkeit")])


class SpeedNumber(MerachEntity, NumberEntity):
    _attr_icon = "mdi:speedometer"
    _attr_device_class = NumberDeviceClass.SPEED
    _attr_native_unit_of_measurement = UnitOfSpeed.KILOMETERS_PER_HOUR
    _attr_native_min_value = MIN_SPEED
    _attr_native_max_value = MAX_SPEED
    _attr_native_step = 0.1
    _attr_mode = NumberMode.SLIDER

    @property
    def native_value(self) -> float | None:
        state = self._device.state
        return state.speed if state.status == STATUS_RUNNING else None

    async def async_set_native_value(self, value: float) -> None:
        await self._device.async_set_speed(value)
