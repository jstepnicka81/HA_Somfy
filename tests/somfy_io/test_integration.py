"""Run in a network-isolated HA 2026.9.0 container; no real gateway access."""
import asyncio
import copy
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import aiohttp
from aiohttp import web
from homeassistant import config_entries, loader
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import device_registry as dr, area_registry as ar, floor_registry as fr, label_registry as lr, frame

from custom_components.somfy_io_local.api import Gateway, GatewayError, GatewayAuthError
from custom_components.somfy_io_local.model import (
    DOMAIN, import_tahoma, merge_import, gateway_devices, position_from_state,
    validate_inventory, host_address,
)

G1, G2 = "esp-000000000001", "esp-000000000002"
D1, D2 = "io-000001", "io-000002"
TOKEN = "a" * 64


def device(address=1):
    return {"id": f"io-{address:06x}", "address": address, "name": f"Test {address}", "kind": "shutter"}


def tahoma(address=1, widget="PositionableRollerShutter"):
    return {"deviceURL": f"io://1234-5678-9012/{address}", "label": f"Test {address}",
            "definition": {"widgetName": widget}}


class ModelTests(unittest.TestCase):
    def test_import_filters_non_covers_and_invalid_addresses(self):
        rows = [tahoma(), tahoma(2, "PositionableExteriorVenetianBlind"),
                tahoma(3, "IOStack"), tahoma(0), tahoma(0xFFFFFF),
                {"deviceURL": "rts://hub/4"}]
        result = import_tahoma(rows)
        self.assertEqual(set(result), {D1, D2})
        self.assertEqual(result[D2]["kind"], "blind")
        self.assertIsNone(result[D1]["gateway"])

    def test_reimport_retains_assignment_and_missing_devices(self):
        old = {D1: {**device(), "gateway": G1}, D2: {**device(2), "gateway": G2}}
        new = import_tahoma([{**tahoma(), "label": "Renamed"}])
        result = merge_import(old, new)
        self.assertEqual(result[D1]["gateway"], G1)
        self.assertEqual(result[D1]["name"], "Renamed")
        self.assertIn(D2, result)
        self.assertEqual(old[D1]["name"], "Test 1")

    def test_duplicate_addresses_are_not_silently_merged(self):
        with self.assertRaises(ValueError):
            import_tahoma([tahoma(), tahoma()])

    def test_capacity_and_host_validation(self):
        devices = {str(i): {**device(i), "gateway": G1} for i in range(1, 34)}
        with self.assertRaises(ValueError):
            gateway_devices(devices, G1)
        for host in ("http://192.0.2.1", "192.0.2.1/path", "user@192.0.2.1"):
            with self.assertRaises(ValueError):
                host_address(host)

    def test_positions_do_not_invent_or_invert_values(self):
        self.assertEqual(position_from_state({"position": 100}), 100)
        self.assertEqual(position_from_state({"position": 0}), 0)
        for value in (None, True, "50", -1, 101, float("nan")):
            self.assertIsNone(position_from_state({"position": value}))


class FakeGateway:
    def __init__(self, gid, node):
        self.id = gid
        self.node = node
        self.devices = []
        self.online = True
        self.motion = False
        self.commands = []
        self.configures = []
        self.fail_configure = False
        self.tilt_supported = True
        self.position = 67
        self.tilt_position = 51.724609375
        self.rssi = -87.5

    async def info(self):
        if not self.online:
            raise GatewayError("offline")
        return {"api_version": 1, "id": self.id, "node": self.node, "devices": copy.deepcopy(self.devices)}

    async def states(self):
        await self.info()
        return {"id": self.id, "node": self.node, "motion_enabled": self.motion,
                "devices": {d["id"]: {"position": self.position, "available": True, "last_result": "response",
                                      "tilt_supported": self.tilt_supported and d["kind"] == "blind",
                                      "tilt_position": self.tilt_position, "rssi_dbm": self.rssi}
                            for d in self.devices}}

    async def configure(self, devices):
        await self.info()
        if self.fail_configure:
            raise GatewayError("uncertain configuration acknowledgement")
        self.devices = copy.deepcopy(devices)
        self.configures.append(copy.deepcopy(devices))

    async def command(self, *args):
        self.commands.append(args)


class HomeAssistantTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        target = Path(self.temp.name) / "custom_components" / DOMAIN
        shutil.copytree(Path(__file__).resolve().parents[2] / "custom_components" / DOMAIN, target)
        self.hass = HomeAssistant(self.temp.name)
        self.hass.config_entries = config_entries.ConfigEntries(self.hass, {})
        loader.async_setup(self.hass)
        dr.async_setup(self.hass)
        frame.async_setup(self.hass)
        for registry in (fr, ar, lr, dr, er):
            await registry.async_load(self.hass)
        self.g1, self.g2 = FakeGateway(G1, 0xf00001), FakeGateway(G2, 0xf00002)
        def factory(session, host, token):
            if token != TOKEN:
                raise GatewayAuthError("bad token")
            return {"192.0.2.1": self.g1, "192.0.2.2": self.g2}[host]
        self.patches = [patch(f"custom_components.{DOMAIN}.{module}.Gateway", side_effect=factory)
                        for module in ("config_flow", "coordinator")]
        self.patches += [patch(f"custom_components.{DOMAIN}.{module}.async_get_clientsession", return_value=None)
                         for module in ("config_flow", "coordinator")]
        for mock in self.patches:
            mock.start()
            self.addCleanup(mock.stop)
        result = await self.hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"}, data={
            "host": "192.0.2.1", "name": "First ESP", "token": TOKEN})
        self.assertEqual(result["type"], "create_entry", result)
        self.entry = result["result"]
        await self.hass.async_block_till_done()
        self.assertEqual(self.entry.state, config_entries.ConfigEntryState.LOADED)

    async def asyncTearDown(self):
        await self.hass.async_stop()
        for mock in self.patches:
            mock.stop()
        self.temp.cleanup()

    async def option(self, step, data):
        result = await self.hass.config_entries.options.async_init(self.entry.entry_id)
        result = await self.hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": step})
        result = await self.hass.config_entries.options.async_configure(result["flow_id"], data)
        await self.hass.async_block_till_done()
        return result

    async def prepare_two_gateways(self):
        result = await self.option("gateway", {"host": "192.0.2.2", "name": "Second ESP", "token": TOKEN})
        self.assertEqual(result["type"], "create_entry", result)
        result = await self.option("import_json", {"devices_json": json.dumps([tahoma(), tahoma(2)])})
        self.assertEqual(result["type"], "create_entry", result)
        for did, gid in ((D1, G1), (D2, G2)):
            result = await self.option("assign", {"device": did, "gateway": gid})
            self.assertEqual(result["type"], "create_entry", result)

    async def test_two_gateways_assignment_move_keeps_entity_and_never_moves_motor(self):
        await self.prepare_two_gateways()
        registry = er.async_get(self.hass)
        entity = registry.async_get_entity_id("cover", DOMAIN, D1)
        self.assertIsNotNone(entity)
        self.assertEqual(self.hass.states.get(entity).attributes["current_position"], 67)
        result = await self.option("assign", {"device": D1, "gateway": G2})
        self.assertEqual(result["type"], "create_entry", result)
        self.assertEqual(self.g1.devices, [])
        self.assertEqual({d["id"] for d in self.g2.devices}, {D1, D2})
        self.assertEqual(registry.async_get_entity_id("cover", DOMAIN, D1), entity)
        self.assertEqual(self.g1.commands + self.g2.commands, [])

    async def test_offline_old_gateway_blocks_move(self):
        await self.prepare_two_gateways()
        self.g1.online = False
        result = await self.option("assign", {"device": D1, "gateway": G2})
        self.assertEqual(result["errors"]["base"], "assignment_failed")
        self.assertEqual(self.entry.options["devices"][D1]["gateway"], G1)
        self.assertNotIn(D1, {d["id"] for d in self.g2.devices})

    async def test_unconfirmed_revocation_does_not_grant_new_owner(self):
        await self.prepare_two_gateways()
        self.g1.fail_configure = True
        result = await self.option("assign", {"device": D1, "gateway": G2})
        self.assertEqual(result["errors"]["base"], "assignment_failed")
        self.assertEqual(self.entry.options["devices"][D1]["gateway"], G1)
        self.assertNotIn(D1, {d["id"] for d in self.g2.devices})

    async def test_new_owner_offline_after_revocation_recovers_without_dual_ownership(self):
        await self.prepare_two_gateways()
        self.g2.online = False
        result = await self.option("assign", {"device": D1, "gateway": G2})
        self.assertEqual(result["type"], "create_entry", result)
        self.assertEqual(self.g1.devices, [])
        self.g2.online = True
        await self.hass.data[DOMAIN][self.entry.entry_id].async_refresh()
        self.assertEqual({d["id"] for d in self.g2.devices}, {D1, D2})
        self.assertEqual(self.g1.commands + self.g2.commands, [])

    async def test_mock_commands_route_only_to_assigned_gateway(self):
        await self.prepare_two_gateways()
        self.g2.motion = True
        await self.hass.data[DOMAIN][self.entry.entry_id].async_refresh()
        entity = er.async_get(self.hass).async_get_entity_id("cover", DOMAIN, D2)
        for service, values in (("open_cover", {}), ("close_cover", {}),
                                ("set_cover_position", {"position": 67}), ("stop_cover", {})):
            await self.hass.services.async_call("cover", service, {"entity_id": entity, **values}, blocking=True)
        self.assertEqual(self.g1.commands, [])
        self.assertEqual(self.g2.commands, [(D2, "position", 100), (D2, "position", 0),
                                           (D2, "position", 67), (D2, "stop", None)])

    async def test_signal_sensor_shares_device_and_follows_gateway_assignment(self):
        await self.prepare_two_gateways()
        registry = er.async_get(self.hass)
        sensor = registry.async_get_entity_id("sensor", DOMAIN, D1 + "-rssi")
        cover = registry.async_get_entity_id("cover", DOMAIN, D1)
        state = self.hass.states.get(sensor)
        self.assertEqual(state.state, "-87.5")
        self.assertEqual(state.attributes["unit_of_measurement"], "dBm")
        self.assertEqual(registry.async_get(sensor).device_id, registry.async_get(cover).device_id)
        self.assertEqual(registry.async_get(sensor).entity_category, "diagnostic")
        self.g2.rssi = -101.0
        await self.option("assign", {"device": D1, "gateway": G2})
        self.assertEqual(registry.async_get_entity_id("sensor", DOMAIN, D1 + "-rssi"), sensor)
        self.assertEqual(float(self.hass.states.get(sensor).state), -101)
        self.assertEqual(self.g1.commands + self.g2.commands, [])

    async def test_signal_missing_invalid_stale_or_offline_is_unavailable(self):
        await self.prepare_two_gateways()
        sensor = er.async_get(self.hass).async_get_entity_id("sensor", DOMAIN, D1 + "-rssi")
        coordinator = self.hass.data[DOMAIN][self.entry.entry_id]
        for value in (None, True, "-80", 1, -128, float("nan")):
            self.g1.rssi = value
            await coordinator.async_refresh()
            self.assertEqual(self.hass.states.get(sensor).state, "unavailable")
        self.g1.rssi = -90
        await coordinator.async_refresh()
        self.assertEqual(float(self.hass.states.get(sensor).state), -90)
        self.g1.online = False
        await coordinator.async_refresh()
        self.assertEqual(self.hass.states.get(sensor).state, "unavailable")

    async def test_blind_height_and_tilt_are_independent_and_not_optimistic(self):
        await self.prepare_two_gateways()
        await self.option("import_json", {"devices_json": json.dumps([tahoma(2, "PositionableExteriorVenetianBlind")])})
        entity = er.async_get(self.hass).async_get_entity_id("cover", DOMAIN, D2)
        self.g2.motion = True
        coordinator = self.hass.data[DOMAIN][self.entry.entry_id]
        await coordinator.async_refresh()
        state = self.hass.states.get(entity)
        self.assertEqual(state.attributes["current_position"], 67)
        self.assertEqual(state.attributes["current_tilt_position"], 52)
        await self.hass.services.async_call("cover", "set_cover_tilt_position",
                                           {"entity_id": entity, "tilt_position": 100}, blocking=True)
        await self.hass.services.async_call("cover", "set_cover_position",
                                           {"entity_id": entity, "position": 30}, blocking=True)
        self.assertEqual(self.g1.commands, [])
        self.assertEqual(self.g2.commands, [(D2, "tilt", 100), (D2, "position", 30)])
        state = self.hass.states.get(entity)
        self.assertEqual(state.attributes["current_position"], 67)
        self.assertEqual(state.attributes["current_tilt_position"], 52)
        self.g2.tilt_position = None
        await coordinator.async_refresh()
        self.assertIsNone(self.hass.states.get(entity).attributes.get("current_tilt_position"))
        self.assertEqual(self.hass.states.get(entity).attributes["current_position"], 67)
        self.g2.position, self.g2.tilt_position = None, 0
        await coordinator.async_refresh()
        self.assertIsNone(self.hass.states.get(entity).attributes.get("current_position"))
        self.assertEqual(self.hass.states.get(entity).attributes["current_tilt_position"], 0)

    async def test_tilt_is_locked_and_not_advertised_on_shutters_or_old_firmware(self):
        from homeassistant.components.cover import CoverEntityFeature
        from homeassistant.exceptions import HomeAssistantError
        await self.prepare_two_gateways()
        registry = er.async_get(self.hass)
        shutter = registry.async_get_entity_id("cover", DOMAIN, D1)
        self.assertFalse(self.hass.states.get(shutter).attributes["supported_features"] & CoverEntityFeature.SET_TILT_POSITION)
        await self.option("import_json", {"devices_json": json.dumps([tahoma(2, "PositionableExteriorVenetianBlind")])})
        blind = registry.async_get_entity_id("cover", DOMAIN, D2)
        with self.assertRaises(HomeAssistantError):
            await self.hass.services.async_call("cover", "set_cover_tilt_position",
                                               {"entity_id": blind, "tilt_position": 50}, blocking=True)
        self.assertEqual(self.g2.commands, [])
        self.g2.tilt_supported = False
        await self.hass.data[DOMAIN][self.entry.entry_id].async_refresh()
        self.assertFalse(self.hass.states.get(blind).attributes["supported_features"] & CoverEntityFeature.SET_TILT_POSITION)

    async def test_reimport_preserves_entity_and_owner(self):
        await self.prepare_two_gateways()
        registry = er.async_get(self.hass)
        entity = registry.async_get_entity_id("cover", DOMAIN, D1)
        result = await self.option("import_json", {"devices_json": json.dumps([{**tahoma(), "label": "New name"}])})
        self.assertEqual(result["type"], "create_entry", result)
        self.assertEqual(self.entry.options["devices"][D1]["gateway"], G1)
        self.assertIn(D2, self.entry.options["devices"])
        self.assertEqual(registry.async_get_entity_id("cover", DOMAIN, D1), entity)

    async def test_esp_restart_with_empty_config_restores_inventory(self):
        await self.prepare_two_gateways()
        self.g1.devices = []
        self.g1.online = False
        coordinator = self.hass.data[DOMAIN][self.entry.entry_id]
        await coordinator.async_refresh()
        self.g1.online = True
        await coordinator.async_refresh()
        self.assertEqual([d["id"] for d in self.g1.devices], [D1])
        self.assertEqual(self.g1.commands, [])

    async def test_one_offline_gateway_does_not_hide_other_covers(self):
        await self.prepare_two_gateways()
        self.g1.online = False
        coordinator = self.hass.data[DOMAIN][self.entry.entry_id]
        await coordinator.async_refresh()
        registry = er.async_get(self.hass)
        self.assertEqual(self.hass.states.get(registry.async_get_entity_id("cover", DOMAIN, D1)).state, "unavailable")
        self.assertEqual(self.hass.states.get(registry.async_get_entity_id("cover", DOMAIN, D2)).state, "open")

    async def test_locked_motion_rejects_service_without_command(self):
        await self.prepare_two_gateways()
        entity = er.async_get(self.hass).async_get_entity_id("cover", DOMAIN, D1)
        from homeassistant.exceptions import HomeAssistantError
        with self.assertRaises(HomeAssistantError):
            await self.hass.services.async_call("cover", "open_cover", {"entity_id": entity}, blocking=True)
        self.assertEqual(self.g1.commands, [])

    async def test_duplicate_radio_identity_is_rejected(self):
        self.g2.node = self.g1.node
        result = await self.option("gateway", {"host": "192.0.2.2", "name": "Duplicate", "token": TOKEN})
        self.assertEqual(result["errors"]["base"], "ownership_conflict")

    async def test_tahoma_import_uses_only_verified_get_and_does_not_store_token(self):
        calls = []
        raw = json.dumps([tahoma()]).encode()
        class Content:
            async def iter_chunked(self, size):
                yield raw[:8]
                yield raw[8:]
        class Response:
            status = 200
            content = Content()
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                return False
        class Session:
            def get(self, url, **kwargs):
                calls.append((url, kwargs))
                return Response()
        with patch(f"custom_components.{DOMAIN}.config_flow.async_get_clientsession", return_value=Session()):
            result = await self.option("tahoma", {"host": "192.0.2.10", "pin": "1234-5678-9012", "token": "test-tahoma-secret"})
        self.assertEqual(result["type"], "create_entry", result)
        self.assertEqual(len(calls), 1)
        url, kwargs = calls[0]
        self.assertTrue(url.endswith("/setup/devices"))
        self.assertEqual(kwargs["server_hostname"], "gateway-1234-5678-9012.local")
        self.assertTrue(kwargs["ssl"].check_hostname)
        self.assertFalse(kwargs["allow_redirects"])
        self.assertNotIn("test-tahoma-secret", json.dumps(dict(self.entry.options)))
        self.assertEqual(self.g1.commands, [])

    async def test_conflicting_esp_inventory_is_rejected(self):
        await self.prepare_two_gateways()
        self.g2.devices.append(device())
        result = await self.option("gateway", {"host": "192.0.2.2", "name": "Conflict", "token": TOKEN})
        self.assertEqual(result["errors"]["base"], "ownership_conflict")


class TransportTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.calls = []
        self.status = 200
        self.payload = {"api_version": 1, "id": G1, "node": 0xf00001, "devices": []}
        async def handler(request):
            self.calls.append((request.method, request.path, request.headers.get("Authorization")))
            if self.status != 200:
                return web.Response(status=self.status)
            # Deliberately split JSON across chunks to test real transport framing.
            response = web.StreamResponse()
            await response.prepare(request)
            raw = json.dumps(self.payload).encode()
            await response.write(raw[:10])
            await asyncio.sleep(0.001)
            await response.write(raw[10:])
            return response
        app = web.Application()
        app.router.add_route("*", "/{path:.*}", handler)
        self.runner = web.AppRunner(app)
        await self.runner.setup()
        site = web.TCPSite(self.runner, "127.0.0.1", 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]
        self.session = aiohttp.ClientSession()
        self.client = Gateway(self.session, "127.0.0.1", TOKEN)
        self.client.base = f"http://127.0.0.1:{port}"

    async def asyncTearDown(self):
        await self.session.close()
        await self.runner.cleanup()

    async def test_fragmented_inventory(self):
        self.assertEqual((await self.client.info())["id"], G1)
        self.assertEqual(self.calls[0], ("GET", "/api/v1/info", "Bearer " + TOKEN))

    async def test_command_failure_is_not_retried(self):
        self.status = 503
        with self.assertRaises(GatewayError):
            await self.client.command(D1, "position", 67)
        self.assertEqual(len(self.calls), 1)

    async def test_auth_failure(self):
        self.status = 401
        with self.assertRaises(GatewayAuthError):
            await self.client.info()

    async def test_redirect_never_forwards_token(self):
        self.status = 302
        with self.assertRaises(GatewayError):
            await self.client.info()
        self.assertEqual(len(self.calls), 1)

    async def test_invalid_position_never_sends(self):
        for action in ("position", "tilt"):
            for position in (-1, 101, True, "50"):
                with self.assertRaises(ValueError):
                    await self.client.command(D1, action, position)
        self.assertEqual(self.calls, [])

    async def test_tilt_transport_body(self):
        from unittest.mock import AsyncMock
        self.client.request = AsyncMock(return_value={"result": "accepted"})
        await self.client.command(D1, "tilt", 50)
        method, path, body = self.client.request.call_args.args
        self.assertEqual((method, path), ("POST", "/api/v1/command"))
        self.assertEqual((body["id"], body["action"], body["position"]), (D1, "tilt", 50))
        self.assertEqual(len(body["request_id"]), 32)

    async def test_oversized_response_is_rejected(self):
        self.payload = {"oversize": "x" * 70000}
        with self.assertRaises(GatewayError):
            await self.client.info()


if __name__ == "__main__":
    unittest.main(verbosity=2)
