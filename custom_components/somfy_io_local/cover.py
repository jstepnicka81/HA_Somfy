"""Stable identities are independent of which ESP owns a motor."""
from homeassistant.components.cover import CoverEntity, CoverEntityFeature, CoverDeviceClass
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from .api import GatewayError
from .model import DOMAIN, position_from_state


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(LocalCover(coordinator, row) for row in coordinator.config["devices"].values())


class LocalCover(CoordinatorEntity, CoverEntity):
    _attr_has_entity_name = True
    _attr_name = None
    _attr_supported_features = (CoverEntityFeature.OPEN | CoverEntityFeature.CLOSE |
                                CoverEntityFeature.STOP | CoverEntityFeature.SET_POSITION)

    def __init__(self, coordinator, device):
        super().__init__(coordinator)
        self.device = device
        self._attr_unique_id = device["id"]
        self._attr_device_class = CoverDeviceClass.BLIND if device["kind"] == "blind" else CoverDeviceClass.SHUTTER
        self._attr_device_info = {
            "identifiers": {(DOMAIN, device["id"])}, "name": device["name"],
            "manufacturer": "Somfy", "model": "io-homecontrol",
        }

    @property
    def gateway_state(self):
        return (self.coordinator.data or {}).get(self.device.get("gateway")) or {}

    @property
    def motor_state(self):
        return self.gateway_state.get("devices", {}).get(self.device["id"], {})

    @property
    def available(self):
        return bool(self.gateway_state and self.motor_state.get("available"))

    @property
    def current_cover_position(self):
        return position_from_state(self.motor_state) if self.available else None

    @property
    def tilt_supported(self):
        return self.device["kind"] == "blind" and self.motor_state.get("tilt_supported") is True

    @property
    def supported_features(self):
        features = self._attr_supported_features
        if self.tilt_supported:
            features |= CoverEntityFeature.SET_TILT_POSITION
        return features

    @property
    def current_cover_tilt_position(self):
        if self.available and self.tilt_supported:
            return position_from_state(self.motor_state, "tilt_position")
        return None

    @property
    def is_closed(self):
        position = self.current_cover_position
        return None if position is None else position == 0

    @property
    def extra_state_attributes(self):
        return {"esp": self.device.get("gateway"),
                "motion_enabled": self.gateway_state.get("motion_enabled", False),
                "last_result": self.motor_state.get("last_result")}

    async def _command(self, action, position=None):
        gid = self.device.get("gateway")
        if not gid or not self.gateway_state or gid not in self.coordinator.configured:
            raise HomeAssistantError("Assigned ESP is unavailable")
        if not self.gateway_state.get("motion_enabled"):
            raise HomeAssistantError("Movement is locked on the ESP")
        try:
            await self.coordinator.clients[gid].command(self.device["id"], action, position)
        except GatewayError as err:
            # Do not retry: lost acknowledgement does not prove a command failed.
            raise HomeAssistantError(str(err)) from err
        await self.coordinator.async_request_refresh()

    async def async_open_cover(self, **kwargs):
        await self._command("position", 100)

    async def async_close_cover(self, **kwargs):
        await self._command("position", 0)

    async def async_set_cover_position(self, **kwargs):
        await self._command("position", kwargs["position"])

    async def async_stop_cover(self, **kwargs):
        await self._command("stop")

    async def async_set_cover_tilt_position(self, **kwargs):
        if not self.tilt_supported:
            raise HomeAssistantError("Assigned ESP does not support slat tilt for this device")
        await self._command("tilt", kwargs["tilt_position"])
