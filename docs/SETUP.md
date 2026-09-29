# Installation and setup

## Hardware and initial flash

TTGO LoRa32 / ESP32 with SX1276: SPI SCK 5, MISO 19, MOSI 27, CS 18,
radio reset 14. The radio hardware must support the applicable band. The
firmware uses FSK, not LoRa, on 868.25 / 868.95 / 869.85 MHz and assumes a
32 MHz radio oscillator. OLED support is not implemented. Check pinout and
RF hardware before using a different board.

An initial installation on a new board needs the bootloader, partition table
and application:

```sh
python -m platformio run --project-dir ttgo-io-gateway --target upload --upload-port PORT
```

Replace `PORT` with the actual serial port. Back up any existing firmware
privately before flashing. Preserve NVS: it holds the radio identity, io key
and network configuration. On a board previously updated over OTA, `app0` may
not be the active slot. Prefer OTA for subsequent updates instead of blindly
writing an application to a fixed offset. Never clone a complete NVS image to
another ESP; each gateway requires a distinct radio identity.

## Credentials and the io key

See [KEY_TRANSFER.md](KEY_TRANSFER.md) if you do not already have a verified io
system key. Key transfer is not implemented in the public gateway firmware.

```sh
python tools/provision_io_gateway.py init private/gateway.json
```

The command generates a fresh API token with motion and polling disabled.
Edit this private file with your own SSID and Wi-Fi password. Store your io
system key separately in `private/io-key.json`: a JSON object with a `key_hex`
property containing your own 32-character hexadecimal key. No working example
credentials are distributed. `private/` is ignored by Git.

```sh
python tools/provision_io_gateway.py apply private/gateway.json --port PORT --io-key-file private/io-key.json
```

Restart the ESP after the save acknowledgement. If it already holds the correct
key in NVS, omit `--io-key-file`. The tool refuses to replace a different stored
key. Motion and polling are disabled by default. For normal operation, set both
`polling_enabled` and `motion_enabled` to `true` in the private JSON, apply it
with `--allow-motion`, and restart. Polling can be enabled separately for status
queries. The tool does not print credentials to the console.

## OTA updates

```sh
python tools/ota_io_gateway.py --host 192.0.2.10 --config private/gateway.json --firmware ttgo-io-gateway/.pio/build/ttgo-io-gateway/firmware.bin
```

The address is a documentation example. Use your ESP's actual address. Upload
only an application `firmware.bin`, never a complete flash backup. The client
includes the image size and SHA-256. The ESP checks the token, image format and
hash. An active RF transaction or pending command causes HTTP 409 (busy).
A lost acknowledgement must not trigger a blind retry: check `/api/v1/info`
first. Success activates the other application slot and restarts the ESP.
NVS and motion/polling settings are preserved. Automatic rollback after an
unbootable application is not implemented.

## TaHoma import and multiple gateways

The import reads only the device list through the local API, verifying both
the public Overkiz CA and the gateway TLS hostname. The TaHoma token is not
stored by the integration. Alternatively, import your own device-list JSON;
keep the original export private. Positionable roller shutters and exterior
venetian blinds are recognized. Moving a device between gateways requires the
old gateway to acknowledge removal, preventing two simultaneous owners.
