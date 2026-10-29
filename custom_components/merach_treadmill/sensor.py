"""Sensoren des Laufbands."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import UnitOfLength, UnitOfSpeed, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import MerachConfigEntry
from .const import STATUS_NAMES
from .device import MerachTreadmill, TreadmillState
from .entity import MerachEntity


@dataclass(frozen=True, kw_only=True)
class MerachSensorDescription(SensorEntityDescription):
    value_fn: Callable[[TreadmillState], float | int | str | None]
    label: str


def _status(state: TreadmillState) -> str | None:
    if state.status is None:
        return None
    return STATUS_NAMES.get(state.status, f"Unbekannt ({state.status})")


SENSORS = (
    MerachSensorDescription(
        key="status",
        label="Status",
        icon="mdi:run",
        value_fn=_status,
    ),
    MerachSensorDescription(
        key="speed",
        label="Geschwindigkeit",
        device_class=SensorDeviceClass.SPEED,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfSpeed.KILOMETERS_PER_HOUR,
        suggested_display_precision=1,
        value_fn=lambda s: s.speed,
    ),
    MerachSensorDescription(
        key="elapsed",
        label="Trainingszeit",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        value_fn=lambda s: s.elapsed,
    ),
    MerachSensorDescription(
        key="distance",
        label="Distanz",
        device_class=SensorDeviceClass.DISTANCE,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfLength.METERS,
        value_fn=lambda s: s.distance,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MerachConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    device = entry.runtime_data
    async_add_entities(MerachSensor(device, desc) for desc in SENSORS)


class MerachSensor(MerachEntity, SensorEntity):
    """Ein Messwert des Laufbands."""

    entity_description: MerachSensorDescription

    def __init__(self, device: MerachTreadmill, description: MerachSensorDescription) -> None:
        super().__init__(device, description.key, description.label)
        self.entity_description = description

    @property
    def native_value(self) -> float | int | str | None:
        return self.entity_description.value_fn(self._device.state)
