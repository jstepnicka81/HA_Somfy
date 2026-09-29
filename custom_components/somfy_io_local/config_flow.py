"""UI for ESP discovery, TaHoma import and explicit ownership changes."""
import copy
import json
import re
import ssl
from functools import partial
from pathlib import Path
import aiohttp
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from .api import Gateway, GatewayError, GatewayAuthError, bounded_json
from .model import DOMAIN, gateway_devices, host_address, import_tahoma, merge_import


def gateway_schema():
    return vol.Schema({vol.Required("host"): str, vol.Required("name"): str,
                       vol.Required("token"): selector.TextSelector(
                           selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD))})


async def read_gateway(hass, data):
    if not re.fullmatch(r"[0-9a-fA-F]{64}", data["token"]):
        raise ValueError("Token must be 64 hexadecimal characters")
    host = host_address(data["host"])
    info = await Gateway(async_get_clientsession(hass), host, data["token"]).info()
    return info, {"host": host, "token": data["token"], "name": data["name"], "node": info["node"]}


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")
        errors = {}
        if user_input is not None:
            try:
                info, gateway = await read_gateway(self.hass, user_input)
                devices = {row["id"]: {**row, "gateway": info["id"]} for row in info["devices"]}
                return self.async_create_entry(title="Somfy io Local", data={
                    "gateways": {info["id"]: gateway}, "devices": devices})
            except GatewayAuthError:
                errors["base"] = "invalid_auth"
            except GatewayError:
                errors["base"] = "cannot_connect"
            except ValueError:
                errors["base"] = "invalid_input"
        return self.async_show_form(step_id="user", data_schema=gateway_schema(), errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return OptionsFlow()


class OptionsFlow(config_entries.OptionsFlow):
    def config(self):
        return copy.deepcopy(dict(self.config_entry.options or self.config_entry.data))

    async def async_step_init(self, user_input=None):
        return self.async_show_menu(step_id="init", menu_options=["gateway", "tahoma", "import_json", "assign"])

    async def async_step_gateway(self, user_input=None):
        errors = {}
        if user_input is not None:
            try:
                info, gateway = await read_gateway(self.hass, user_input)
                config = self.config()
                for gid, existing in config["gateways"].items():
                    if gid != info["id"] and existing["node"] == info["node"]:
                        raise ValueError("Duplicate radio identity")
                # Adopt stored devices only when they have no different owner.
                for row in info["devices"]:
                    old = config["devices"].get(row["id"])
                    if old and old.get("gateway") not in (None, info["id"]):
                        raise ValueError("ESP already owns a device assigned elsewhere")
                config["gateways"][info["id"]] = gateway
                for row in info["devices"]:
                    config["devices"][row["id"]] = {**row, "gateway": info["id"]}
                return self.async_create_entry(title="", data=config)
            except GatewayAuthError:
                errors["base"] = "invalid_auth"
            except GatewayError:
                errors["base"] = "cannot_connect"
            except ValueError:
                errors["base"] = "ownership_conflict"
        return self.async_show_form(step_id="gateway", data_schema=gateway_schema(), errors=errors)

    def import_result(self, rows):
        incoming = import_tahoma(rows)
        if not incoming:
            raise ValueError("No compatible covers")
        config = self.config()
        config["devices"] = merge_import(config["devices"], incoming)
        return self.async_create_entry(title="", data=config)

    async def async_step_import_json(self, user_input=None):
        errors = {}
        if user_input is not None:
            try:
                return self.import_result(json.loads(user_input["devices_json"]))
            except (ValueError, KeyError, TypeError, AttributeError):
                errors["base"] = "invalid_input"
        return self.async_show_form(step_id="import_json", errors=errors, data_schema=vol.Schema({
            vol.Required("devices_json"): selector.TextSelector(selector.TextSelectorConfig(multiline=True))}))

    async def async_step_tahoma(self, user_input=None):
        errors = {}
        if user_input is not None:
            try:
                host = host_address(user_input["host"])
                pin = user_input["pin"]
                if not re.fullmatch(r"\d{4}-\d{4}-\d{4}", pin):
                    raise ValueError("Invalid gateway PIN")
                # Dedicated public CA, verified hostname even when connecting by IP.
                context = await self.hass.async_add_executor_job(
                    partial(ssl.create_default_context,
                            cafile=str(Path(__file__).with_name("overkiz-root-ca.pem"))))
                session = async_get_clientsession(self.hass)
                async with session.get(
                    f"https://{host}:8443/enduser-mobile-web/1/enduserAPI/setup/devices",
                    ssl=context, server_hostname=f"gateway-{pin}.local",
                    headers={"Authorization": "Bearer " + user_input["token"]},
                    timeout=aiohttp.ClientTimeout(total=15), allow_redirects=False,
                ) as response:
                    if response.status != 200:
                        raise ValueError("Import failed")
                    return self.import_result(await bounded_json(response, 1048576))
            except (ValueError, KeyError, TypeError, AttributeError, OSError, aiohttp.ClientError, TimeoutError):
                errors["base"] = "import_failed"
        return self.async_show_form(step_id="tahoma", errors=errors, data_schema=vol.Schema({
            vol.Required("host"): str, vol.Required("pin"): str,
            vol.Required("token"): selector.TextSelector(selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD))}))

    async def async_step_assign(self, user_input=None):
        config = self.config()
        if not config["devices"]:
            return self.async_abort(reason="no_devices")
        errors = {}
        if user_input is not None:
            try:
                device = config["devices"][user_input["device"]]
                old = device.get("gateway")
                new = user_input["gateway"]
                if new == "unassigned":
                    new = None
                if new is not None and new not in config["gateways"]:
                    raise ValueError("Unknown ESP")
                device["gateway"] = new
                if new:
                    gateway_devices(config["devices"], new)  # Validate capacity before revocation.
                if old and old != new:
                    # Revoke and persist on OLD ESP before recording the new owner.
                    # An unreachable old ESP blocks reassignment; no unsafe force option.
                    g = config["gateways"][old]
                    client = Gateway(async_get_clientsession(self.hass), g["host"], g["token"])
                    info = await client.info()
                    if info["id"] != old:
                        raise GatewayError("ESP identity changed")
                    coordinator = self.hass.data[DOMAIN][self.config_entry.entry_id]
                    async with coordinator.management_lock:
                        await client.configure(gateway_devices(config["devices"], old))
                        # Do not let an in-flight poll restore old ownership before reload.
                        coordinator.config["devices"][device["id"]]["gateway"] = new
                return self.async_create_entry(title="", data=config)
            except (GatewayError, ValueError, KeyError):
                errors["base"] = "assignment_failed"
        return self.async_show_form(step_id="assign", errors=errors, data_schema=vol.Schema({
            vol.Required("device"): vol.In({k: d["name"] for k, d in config["devices"].items()}),
            vol.Required("gateway"): vol.In({"unassigned": "—", **{k: g["name"] for k, g in config["gateways"].items()}})}))
