# Somfy io Local ESP

A local Home Assistant integration and ESP32/SX1276 firmware for io-homecontrol
roller shutters and exterior venetian blinds. Commands go directly from an ESP
to the motors, without MQTT or a cloud control path.

- Multiple ESP gateways with explicit per-device assignments.
- Device import from a local TaHoma API or a saved device-list JSON file.
- Independent height and slat-tilt control, with actual motor feedback.
- Per-motor signal-strength diagnostics in dBm.
- Authenticated OTA updates with image and SHA-256 validation.

Development versions: **firmware 0.2.2**, **HA integration 0.2.1**. The public
firmware contains the operational gateway, not the original experimental
key-transfer receiver. Source builds are provided; personal flash/NVS backups
and installation credentials are not included. The default documentation,
command-line messages and HA interface are English; Czech remains an optional
HA translation.

## Requirements

- ESP32 with an SX1276 radio for the applicable European band; tested on TTGO LoRa32.
- Home Assistant; the integration tests use Core 2026.9.0.
- An existing **16-byte io system key belonging to your installation**.
- Python 3.10+ and PlatformIO for builds; Docker for isolated integration tests.
- A trusted local network. The ESP API uses HTTP with a bearer token, not TLS.

**Key onboarding is not automated by this public release.** If you do not
already have your io key or a compatible key-transfer receiver, this repository
alone cannot complete first-time onboarding. The procedure below records what
worked during development and explains that remaining tooling requirement.

## Obtaining the io key for your motors

There are three different credentials; they are not interchangeable:

| Credential | Purpose | Where it belongs |
|---|---|---|
| io system key: 16 bytes / 32 hex characters | Authenticates radio commands to compatible motors | ESP NVS; optional private import file |
| ESP API token: 32 random bytes / 64 hex characters | Authenticates HA and OTA requests to an ESP | Private gateway configuration and HA |
| TaHoma local API token | Imports the TaHoma device list | Entered for import; not saved by this integration |

A TaHoma device-list export, gateway PIN, or local API token does **not** give
this integration the radio system key. In the tested installation one shared
key worked for several motors; do not assume every motor in every installation
shares the same key.

### If you already have the key

Keep it in an ignored local file, `private/io-key.json`, as a JSON object whose
`key_hex` property contains your own 32-character hexadecimal key. Do not use a
sample value, put it in source code, or include the file in an issue or commit.
Import it using the USB command under [Provisioning](#provisioning).

If this ESP already holds the verified key in NVS under `io-receiver/key`, keep
NVS intact and omit `--io-key-file`. Do not repeat key transfer unnecessarily.

### The TaHoma transfer workflow that worked during development

This was tested with an owner-controlled TaHoma Switch and an experimental
TTGO receiver. That receiver is **not included** here. Its old `K`, `P` and `X`
serial commands are not commands of the public gateway firmware.

1. Prepare a separate compatible io key-transfer receiver. Configure it with
   your own TaHoma radio address and a distinct receiver identity. Prefer a
   spare ESP; keep any existing ESP flash/NVS backup private.
2. Record an ordinary authenticated exchange between your TaHoma and one of
   your motors. Keep the command, six-byte challenge nonce and six-byte MAC
   together: this will independently validate a candidate system key.
3. On the owner account, open the TaHoma key-transfer/send workflow. The tested
   application displayed **Transfer → Remote control**. This is the observed
   wording, not a guarantee that all app versions use the same menu labels.
   Use key transfer, not a reset or generation of a replacement system key.
4. While that send window is open, have the receiver send an addressed
   **CMD 0x38** key-transfer request with its six-byte nonce. Passive listening
   alone did not start the transfer in our test.
5. Receive **CMD 0x32** with the 16-byte wrapped key. In this tested pull flow,
   unwrapping used **CMD 0x38 + request nonce** as the command transcript.
   The CMD 0x31 transcript used by some push examples did not work for this flow.
6. Treat the unwrapped bytes as a **candidate**, not an accepted key. Verify
   them against the independent command/challenge/MAC from step 2. The
   application's "sent" confirmation alone is not proof of a valid stored key.
7. Persist only the verified key. Confirm it survives a receiver reboot, then
   test an authenticated status query. Our development validation also used
   supervised direct motor movements and checked returned positions.
8. Import the verified key into each operational ESP via USB, or retain it in
   the existing NVS. Each ESP needs its own radio identity; never clone a whole
   NVS image between gateways.

The complete follow-up key-transfer handshake was not confirmed in our capture;
validation came from the matching MAC, persistence check and successful direct
motor communication. This is a documented experimental workflow, not a claim
that this repository ships a universal key-extraction tool.

See [Key transfer: evidence, protocol details and failure cases](docs/KEY_TRANSFER.md)
for the transcript details and the mistakes that mattered in our tests.

## Build

```sh
python -m venv .venv
# Linux/macOS: source .venv/bin/activate
# PowerShell: .venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
python -m platformio run --project-dir ttgo-io-gateway
```

The application image is
`ttgo-io-gateway/.pio/build/ttgo-io-gateway/firmware.bin`.
Building does not upload firmware or open a serial port. See
[Hardware and installation](docs/SETUP.md) before flashing a board.

## Provisioning

```sh
python tools/provision_io_gateway.py init private/gateway.json
```

This generates a new random ESP API token and leaves motion and polling
**disabled**. Edit the private file with your own Wi-Fi SSID and password.
Import your verified io key, replacing `PORT` with your actual serial port:

```sh
python tools/provision_io_gateway.py apply private/gateway.json --port PORT --io-key-file private/io-key.json
```

Restart the ESP after a successful acknowledgement. To enable normal operation,
set `polling_enabled` and `motion_enabled` to `true` in your private configuration,
apply it with `--allow-motion`, and restart. Polling may be enabled separately
for a status-only check. An existing different io key is not silently replaced.

## Home Assistant

Copy `custom_components/somfy_io_local` into your HA configuration directory,
check the configuration, and restart Home Assistant. Go to **Settings → Devices
& services → Add integration**, select **Somfy io Local ESP**, and enter the ESP
IP address, a friendly name, and its API token.

Use the integration options to add more ESP gateways, import a TaHoma device
list, and assign each cover to an ESP. A cover has at most one owning gateway;
its entity identity remains stable when moved. Venetian blinds expose separate
slat tilt. Each device has a diagnostic **Signal strength** sensor. Missing or
expired feedback is reported as unavailable rather than replaced with a target.

## OTA and tests

```sh
python tools/ota_io_gateway.py --host 192.0.2.10 --config private/gateway.json --firmware ttgo-io-gateway/.pio/build/ttgo-io-gateway/firmware.bin
python tools/verify.py
```

The IP above is a documentation-only address; replace it with your ESP's address.
OTA preserves NVS and current motion/polling settings. The test command builds
firmware and runs isolated HA and C++ tests. Tests do not open serial devices,
contact your installation or send motor commands. Docker images must be available;
their initial download needs internet access.

## Documentation and licensing

- [Contributor and coding-agent guide](AGENTS.md)
- [Hardware, flashing, provisioning and OTA](docs/SETUP.md)
- [Key-transfer procedure and limitations](docs/KEY_TRANSFER.md)
- [HTTP API and operational behavior](docs/API.md)
- [Preparing a public release](docs/PUBLISHING.md)
- [Validation record](docs/AUDIT.md)
- [Upstream notices](NOTICE) and [GNU GPL v3](LICENSE)

This public distribution uses GPL v3. Originally Apache-2.0 components retain
their notices and license text in `LICENSES/`. This project is not affiliated
with Somfy or Overkiz. RTS motors, end-stop/service configuration, and automatic
failover between gateways are not supported.
