"""Signal strength of the motor's last valid radio reply at its assigned ESP."""
from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.const import EntityCategory, SIGNAL_STRENGTH_DECIBELS_MILLIWATT
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from .model import DOMAIN


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(MotorSignal(coordinator, row) for row in coordinator.config["devices"].values())


class MotorSignal(CoordinatorEntity, SensorEntity):
    _attr_has_entity_name = True
    _attr_translation_key = "signal_strength"
    _attr_device_class = SensorDeviceClass.SIGNAL_STRENGTH
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = SIGNAL_STRENGTH_DECIBELS_MILLIWATT
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, device):
        super().__init__(coordinator)
        self.device = device
        self._attr_unique_id = device["id"] + "-rssi"
        self._attr_device_info = {"identifiers": {(DOMAIN, device["id"])}}

    @property
    def native_value(self):
        gateway = (self.coordinator.data or {}).get(self.device.get("gateway")) or {}
        value = gateway.get("devices", {}).get(self.device["id"], {}).get("rssi_dbm")
        if type(value) in (int, float) and -127.5 <= value <= 0:
            return value
        return None

    @property
    def available(self):
        # A valid radio challenge may arrive even if the position query fails.
        return self.native_value is not None
