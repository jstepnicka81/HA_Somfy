"""USB-only provisioning. Default command only creates a local config, no serial I/O."""
import argparse
import json
from pathlib import Path
import re
import secrets
import time


def validate(config, allow_motion=False):
    if not isinstance(config.get("ssid"), str) or not 1 <= len(config["ssid"].encode()) <= 32:
        raise ValueError("Enter an SSID (1-32 UTF-8 bytes).")
    if not isinstance(config.get("password"), str) or len(config["password"].encode()) > 63:
        raise ValueError("Invalid Wi-Fi password.")
    if not re.fullmatch(r"[0-9a-fA-F]{64}", config.get("token", "")):
        raise ValueError("The token must contain 64 hexadecimal characters.")
    for field in ("motion_enabled", "polling_enabled"):
        if type(config.get(field)) is not bool:
            raise ValueError(f"{field} must be true or false.")
    if config["motion_enabled"] and not allow_motion:
        raise ValueError("Movement is enabled in the file. Explicit --allow-motion is required.")
    if config["motion_enabled"] and not config["polling_enabled"]:
        raise ValueError("Enable polling_enabled as well to receive position feedback when controlling motors.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    init = sub.add_parser("init", help="Create a local configuration file without opening a serial port.")
    init.add_argument("path", type=Path)
    apply = sub.add_parser("apply", help="Open the specified serial port and store the configuration on the ESP.")
    apply.add_argument("path", type=Path)
    apply.add_argument("--port", required=True)
    apply.add_argument("--allow-motion", action="store_true")
    apply.add_argument("--io-key-file", type=Path, help="Optional file containing an existing key_hex; preserves the ESP radio identity.")
    args = parser.parse_args()
    if args.action == "init":
        args.path.parent.mkdir(parents=True, exist_ok=True)
        with args.path.open("x", encoding="utf-8") as stream:
            json.dump({"ssid": "", "password": "", "token": secrets.token_hex(32),
                       "motion_enabled": False, "polling_enabled": False}, stream, indent=2)
        print("Private configuration created. Fill in your Wi-Fi settings; keep the token out of logs.")
        return
    config = json.loads(args.path.read_text(encoding="utf-8-sig"))
    validate(config, args.allow_motion)
    config = {k: config[k] for k in ("ssid", "password", "token", "motion_enabled", "polling_enabled")}
    if args.io_key_file:
        key = json.loads(args.io_key_file.read_text(encoding="utf-8-sig"))["key_hex"]
        if not re.fullmatch(r"[0-9a-fA-F]{32}", key):
            raise ValueError("Invalid io system key.")
        config["io_key"] = key
    import serial
    port = serial.Serial(port=None, baudrate=115200, timeout=0.5, write_timeout=3)
    port.dtr = False
    port.rts = False
    port.port = args.port
    try:
        port.open()
        port.reset_input_buffer()
        port.write(("^" + json.dumps(config, separators=(",", ":")) + "\n").encode())
        port.flush()
        until = time.monotonic() + 8
        while time.monotonic() < until:
            line = port.readline()
            try:
                result = json.loads(line).get("provision")
            except (ValueError, AttributeError):
                continue
            if result == "saved_restart_required":
                print("Saved. The ESP was not restarted. Restart it to apply the configuration.")
                return
            if result:
                raise RuntimeError("The ESP rejected the configuration; check its format and the device state.")
        raise RuntimeError("No acknowledgement received. Check the ESP state before retrying.")
    finally:
        port.close()


if __name__ == "__main__":
    main()
