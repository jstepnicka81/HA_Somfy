"""One installation entry owns the catalog and all ESP gateways."""
from homeassistant.const import Platform
from .coordinator import InstallationCoordinator
from .model import DOMAIN

PLATFORMS = [Platform.COVER, Platform.SENSOR]


async def async_setup_entry(hass, entry):
    coordinator = InstallationCoordinator(hass, entry)
    await coordinator.async_configure()
    await coordinator.async_refresh()
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_reload))
    return True


async def _reload(hass, entry):
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass, entry):
    if await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id)
        return True
    return False
