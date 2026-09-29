"""Cached ESP states; HA polling does not itself transmit radio packets."""
import asyncio
import copy
from datetime import timedelta
import logging
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from .api import Gateway, GatewayError
from .model import gateway_devices

LOGGER = logging.getLogger(__name__)


class InstallationCoordinator(DataUpdateCoordinator):
    def __init__(self, hass, entry):
        super().__init__(hass, LOGGER, config_entry=entry, name="Somfy io Local", update_interval=timedelta(seconds=5))
        self.entry = entry
        self.config = copy.deepcopy(dict(entry.options or entry.data))
        session = async_get_clientsession(hass)
        self.clients = {gid: Gateway(session, g["host"], g["token"])
                        for gid, g in self.config["gateways"].items()}
        self.configured = set()
        self.management_lock = asyncio.Lock()

    async def _configure_one(self, gid):
        async with self.management_lock:
            await self._configure_locked(gid)

    async def _configure_locked(self, gid):
        client = self.clients[gid]
        info = await client.info()
        if info["id"] != gid or info["node"] != self.config["gateways"][gid]["node"]:
            raise GatewayError("ESP identity changed")
        desired = gateway_devices(self.config["devices"], gid)
        actual = [{k: row[k] for k in ("id", "address", "name", "kind")}
                  for row in info["devices"]]
        if sorted(actual, key=lambda row: row["address"]) != desired:
            await client.configure(desired)
        self.configured.add(gid)

    async def async_configure(self):
        for gid in self.clients:
            try:
                await self._configure_one(gid)
            except GatewayError:
                LOGGER.warning("An ESP is unavailable or not configured; its covers stay unavailable")

    async def _async_update_data(self):
        async def fetch(gid, client):
            try:
                if gid not in self.configured:
                    await self._configure_one(gid)
                result = await client.states()
                if result.get("id") != gid or result.get("node") != self.config["gateways"][gid]["node"]:
                    raise GatewayError("ESP identity changed")
                if not isinstance(result.get("devices"), dict):
                    raise GatewayError("Invalid states")
                for state in result["devices"].values():
                    if not isinstance(state, dict) or type(state.get("available")) is not bool:
                        raise GatewayError("Invalid state")
                return gid, result
            except (GatewayError, ValueError, TypeError, KeyError):
                self.configured.discard(gid)
                return gid, None
        return dict(await asyncio.gather(*(fetch(gid, c) for gid, c in self.clients.items())))
