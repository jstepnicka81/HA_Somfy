"""Pure data model; importing and assigning devices never issues RF commands."""
import ipaddress
import re

DOMAIN = "somfy_io_local"
MAX_DEVICES = 32
SUPPORTED_WIDGETS = {"PositionableRollerShutter", "PositionableExteriorVenetianBlind"}


def host_address(value):
    """Only an IP address, never a URL containing credentials or a path."""
    return str(ipaddress.IPv4Address(value.strip()))


def import_tahoma(rows):
    if not isinstance(rows, list):
        raise ValueError("Expected TaHoma device list")
    devices = {}
    for row in rows:
        definition = row.get("definition") or {}
        match = re.fullmatch(r"io://[^/]+/([0-9]+)", row.get("deviceURL", ""))
        if not match or definition.get("widgetName") not in SUPPORTED_WIDGETS:
            continue
        address = int(match[1])
        if not 0 < address < 0xFFFFFF:
            continue
        identity = f"io-{address:06x}"
        if identity in devices:
            raise ValueError("Duplicate radio address")
        devices[identity] = {
            "id": identity, "address": address,
            "name": str(row.get("label") or identity)[:64],
            "kind": "blind" if "Venetian" in definition["widgetName"] else "shutter",
            "gateway": None,
        }
    return devices


def merge_import(existing, incoming):
    """Missing devices are never deleted; existing ownership is preserved."""
    merged = {key: dict(value) for key, value in existing.items()}
    for key, value in incoming.items():
        merged[key] = {**value, "gateway": existing.get(key, {}).get("gateway")}
    return merged


def gateway_devices(devices, gateway_id):
    rows = [{k: d[k] for k in ("id", "address", "name", "kind")}
            for d in devices.values() if d.get("gateway") == gateway_id]
    if len(rows) > MAX_DEVICES:
        raise ValueError("At most 32 devices per ESP")
    return sorted(rows, key=lambda d: d["address"])


def validate_inventory(data):
    if not isinstance(data, dict) or data.get("api_version") != 1:
        raise ValueError("Unsupported ESP API version")
    if not re.fullmatch(r"esp-[0-9a-f]{12}", data.get("id", "")):
        raise ValueError("Invalid ESP identity")
    if type(data.get("node")) is not int or not 0 < data["node"] < 0xFFFFFF:
        raise ValueError("Invalid radio identity")
    if not isinstance(data.get("devices"), list):
        raise ValueError("Missing device list")
    seen = set()
    for row in data.get("devices", []):
        address = row["address"]
        if type(address) is not int or not 0 < address < 0xFFFFFF:
            raise ValueError("Invalid address")
        if row["id"] != f"io-{address:06x}" or address in seen:
            raise ValueError("Invalid/duplicate device identity")
        if row.get("kind") not in ("blind", "shutter"):
            raise ValueError("Invalid device type")
        if not isinstance(row.get("name"), str) or len(row["name"]) > 64:
            raise ValueError("Invalid device name")
        seen.add(address)
    if len(seen) > MAX_DEVICES:
        raise ValueError("Too many devices")
    return data


def position_from_state(state, field="position"):
    value = state.get(field)
    if type(value) not in (int, float) or not 0 <= value <= 100:
        return None
    return round(value)
