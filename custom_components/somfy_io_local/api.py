"""Bounded local HTTP transport. Mutations are never retried automatically."""
import asyncio
import uuid
import json
import aiohttp
from .model import host_address, validate_inventory


class GatewayError(Exception):
    """Error deliberately excludes response bodies, URLs and credentials."""


class GatewayAuthError(GatewayError):
    pass


async def bounded_json(response, limit=65536):
    raw = bytearray()
    async for chunk in response.content.iter_chunked(8192):
        raw.extend(chunk)
        if len(raw) > limit:
            raise ValueError("Response too large")
    return json.loads(raw)


class Gateway:
    def __init__(self, session, host, token):
        self.session = session
        self.base = f"http://{host_address(host)}"
        self.token = token

    async def request(self, method, path, body=None):
        try:
            async with self.session.request(
                method, self.base + path, json=body,
                headers={"Authorization": f"Bearer {self.token}"},
                timeout=aiohttp.ClientTimeout(total=8), allow_redirects=False,
            ) as response:
                if response.status in (401, 403):
                    raise GatewayAuthError("ESP authentication failed")
                if response.status >= 300:
                    raise GatewayError(f"ESP rejected request ({response.status})")
                return await bounded_json(response)
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as err:
            raise GatewayError("ESP communication failed") from err

    async def info(self):
        try:
            return validate_inventory(await self.request("GET", "/api/v1/info"))
        except (ValueError, KeyError, TypeError) as err:
            raise GatewayError("Incompatible ESP inventory") from err

    async def states(self):
        return await self.request("GET", "/api/v1/states")

    async def configure(self, devices):
        return await self.request("PUT", "/api/v1/devices", {"devices": devices})

    async def command(self, device_id, action, position=None):
        body = {"id": device_id, "action": action, "request_id": uuid.uuid4().hex}
        if action not in ("position", "tilt", "stop"):
            raise ValueError("Unsupported action")
        if action in ("position", "tilt"):
            if type(position) is not int or not 0 <= position <= 100:
                raise ValueError("Invalid position")
            body["position"] = position
        return await self.request("POST", "/api/v1/command", body)
