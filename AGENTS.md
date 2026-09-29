# Contributor and coding-agent guide

## Scope and starting points

These instructions apply to this entire repository. It contains a standalone
ESP32/SX1276 gateway and a Home Assistant custom integration for Somfy
io-homecontrol roller shutters and Venetian blinds. Read [README.md](README.md)
first, then [setup](docs/SETUP.md), [the API contract](docs/API.md), and
[key-transfer limitations](docs/KEY_TRANSFER.md) as needed.

Keep documentation, code comments, default UI strings, and command-line messages
in English. The optional Czech translation is intentional. This public tree must
remain self-contained: do not introduce dependencies on a contributor's parent
workspace, private tools, captures, or installed system.

## Repository map

| Path | Responsibility |
| --- | --- |
| `custom_components/somfy_io_local/` | Home Assistant integration; domain `somfy_io_local` |
| `model.py` in the integration | Device import, validation, identifiers, and assignments |
| `config_flow.py` | Setup/options flows, gateway configuration, TaHoma import |
| `api.py` | Authenticated ESP HTTP client, bounded responses, command submission |
| `coordinator.py` | Configuration synchronization and cached-state polling |
| `cover.py`, `sensor.py` | Cover entities and per-motor RSSI sensors |
| `strings.json`, `translations/` | English defaults and translated UI strings |
| `ttgo-io-gateway/platformio.ini` | Pinned firmware toolchain and board configuration |
| `ttgo-io-gateway/src/main.cpp` | Radio initialization, receive loop, and dispatch |
| `src/io_crypto.h` in the firmware | Motor authentication, NVS key/node storage, AES self-test |
| `src/blind_control.h` | Radio transaction state machine and authenticated replies |
| `src/tilt_protocol.h` | Position/tilt parsing and tilt command encoding |
| `src/gateway_state.h`, `src/gateway_policy.h` | Cached state, permission gates, command queue |
| `src/gateway_api.h`, `src/gateway_ota.h` | HTTP API, USB provisioning, and OTA updates |
| `tools/provision_io_gateway.py` | Private configuration creation and explicit USB provisioning |
| `tools/ota_io_gateway.py` | Explicit authenticated firmware upload |
| `tools/verify.py` | Firmware build and isolated HA/native tests |
| `tools/check_public_tree.py` | Publication checks that report paths, not secret values |
| `tests/somfy_io/` | HA integration tests and native C++ protocol/policy tests |
| `docs/` | Installation, API, key transfer, publication guidance, validation record |

## Development and verification

Run commands from the repository root. Use Python 3.10 or newer for the helper
tools and a virtual environment:

```sh
python -m venv .venv
```

Activate it with `source .venv/bin/activate` on Unix, or
`.venv\Scripts\Activate.ps1` in PowerShell, then run:

```sh
python -m pip install -r requirements-dev.txt
python -m platformio run --project-dir ttgo-io-gateway
python tools/verify.py
python tools/check_public_tree.py
```

`verify.py` already includes the firmware build; a separate build is useful when
iterating on firmware only. It also runs HA tests in the pinned Home Assistant
container and native tests with `g++ -std=c++17 -Wall -Wextra -Werror`. Docker must
be available. Initial toolchain, library, and image downloads require internet;
the test containers themselves run with networking disabled and read-only source
mounts. These commands do not open serial devices or contact a live gateway.

The embedded Arduino toolchain uses C++11 constraints even though native tests
use C++17. A passing host test does not replace a firmware build. In particular,
do not rely on newer aggregate-initialization behavior in shared headers.

Scale verification to the change. For documentation-only edits, check links,
examples, and the public-tree scan. For behavior changes, add focused regression
coverage and run the relevant tests; use the full verifier for changes spanning
firmware and HA. Do not claim hardware behavior was tested from an offline pass.
Record what actually ran and any unresolved failures.

## Home Assistant invariants

- Preserve stable device/entity identities across gateway reassignment. A motor
  has at most one owning ESP. Reassignment must revoke ownership on the old
  gateway before configuring the new owner; an unreachable gateway is not proof
  that ownership has been revoked.
- Preserve configuration-flow validation and gateway identity checks. The current
  implementation accepts IPv4 addresses and at most 32 motors per gateway.
- Deep-copy stored entry data/options before editing nested structures. Keep
  configuration synchronization serialized and network work asynchronous.
- One failed gateway must not make other gateways unavailable. Avoid coupling
  RSSI availability to successful position feedback.
- Report measured position and tilt, never a requested target as current state.
  Unknown or expired values stay unknown/unavailable. Advertise tilt controls
  only for blinds whose gateway explicitly reports tilt support.
- Preserve bounded HTTP reads, timeouts, bearer authentication, and redirect
  rejection. Do not automatically retry movement commands. HTTP 202 means
  accepted, not that the motor reached its target.
- HA refreshes read the ESP's cached states. ESP radio polling is a separate
  operation controlled by the firmware polling setting.
- TaHoma import reads the device inventory using verified TLS. Keep certificate
  and expected-hostname validation; do not persist its import token. Importing a
  device list does not obtain a motor authentication key.
- Keep `strings.json` and `translations/en.json` synchronized. Preserve optional
  translation key structure when modifying configuration flows.

## Firmware and protocol invariants

- The radio is SX1276 in FSK mode, not LoRa. Preserve the board pin mapping and
  channel configuration unless intentionally supporting another board. See the
  setup guide before changing radio parameters.
- Validate CRC, packet length, mode, source, destination, and active transaction
  before accepting motor feedback or authentication challenges. Do not update
  a motor's RSSI from unrelated traffic.
- Preserve the distinction between actual position and target position. In the
  current CMD 04 status parser, actual closure is the big-endian value at bytes
  4–5, not target bytes 2–3. HA opening is `100 - raw / 512`.
- Tilt feedback requires the extended response format, sufficient length, and
  selector `0x20`; its value is at bytes 13–14. Keep range checks and independent
  position/tilt validity. Refer to `tilt_protocol.h` and its tests for offsets.
- A tilt-only command uses the `D400` height-preservation sentinel. Keep the
  extended command buffer large enough for the command and its payload; the
  current transaction buffer is nine bytes. A tilt change must not silently
  become a height change.
- Preserve the key/motion/polling gates. Status queries require a key and enabled
  polling; movement and STOP require a key and enabled motion. New provisioning
  defaults to disabled motion and polling. Enabling motion also requires polling.
- Keep the bounded RAM command queue, five-second expiry with wrap-safe time
  arithmetic, and per-motor/per-axis coalescing. Height and tilt requests must
  not overwrite one another. STOP cancels queued work for that motor and can
  preempt its active operation. Do not persist or replay pending commands.
- Keep duplicate request handling and busy responses. Configuration replacement
  and OTA must not race active radio transactions or queued commands.
- Position, tilt, and RSSI age independently. Current cache expiry is 120 seconds;
  missing or expired RSSI is not zero dBm. RSSI reflects a received motor packet,
  not guaranteed bidirectional reachability or a calibrated distance estimate.
- On Wi-Fi loss, pending commands are dropped. Start the HTTP server only after
  the network stack is ready; preserve the existing disconnected-start behavior.

Update the API documentation and regression tests together when deliberately
changing these contracts. Keep protocol observations separate from hypotheses.

## Credentials and public data

Never commit Wi-Fi credentials, API/HA/TaHoma tokens, io system keys, private
certificates, NVS/flash dumps, raw captures, or personal installation inventories.
Do not paste them into logs, test failure output, documentation, or issue reports.
Read private configuration as data rather than embedding secrets in shell text.

Use ignored `private/` files for local configuration. Use documentation addresses
such as `192.0.2.10` and synthetic identities in examples. Test keys and tokens
must be clearly synthetic and unrelated to a real installation. The public AES
known-answer vector and the bundled Overkiz root CA certificate are not private
credentials; preserve their purpose and provenance.

The public gateway imports an owner's existing, verified io key over USB. It does
not implement the historical key-acquisition receiver or serial key export.
Do not describe historical commands as available in this firmware, reintroduce
key export casually, or imply that a TaHoma API token is an io key. The procedure
and unverified parts of the historical exchange are in
[KEY_TRANSFER.md](docs/KEY_TRANSFER.md).

Run the public-tree checker and review the actual diff before publication. The
checker scans Git-listed tracked and untracked non-ignored files for selected
patterns; it cannot prove the absence of every secret or audit Git history.
Ignored files are not automatically safe to share in an archive. Follow
[PUBLISHING.md](docs/PUBLISHING.md) when preparing a release.

## Live hardware and deployment

Default to offline work for development tasks. Firmware upload, USB provisioning,
live RF tests, integration deployment, and HA restarts affect an installation:
perform them only within the owner's requested scope. Honor authorization already
given in the current session without asking again, but never treat an old audit
record or another installation's instructions as permission.

STOP is a motor command, and status polling transmits RF even though it is not a
movement command. Respect any explicit no-motion or no-radio constraint. Never
make a live motor action a routine unit test, discovery step, or build side effect.

Before flashing an existing board, preserve its key, node identity, and network
configuration. Do not erase NVS or assume app0 is active: OTA alternates application
slots. Each ESP needs its own radio node identity. Use the documented update path
and distinguish a blank-board installation from an existing OTA installation.

OTA requires authentication, declared size, SHA-256, and image validation. Keep
failure paths from selecting an incomplete image. A checksum is not a firmware
signature; the current implementation has neither signed updates nor automatic
boot rollback. After a lost upload acknowledgement, inspect the device state
before retrying. OTA preserves existing motion and polling settings.

The current gateway API uses plaintext HTTP on the local network. Do not describe
it as encrypted or expose it publicly as part of setup. Consult the API and setup
guides rather than inventing deployment credentials or addresses.

## Completing a change

Keep firmware and integration versions independent. For a versioned firmware
release, synchronize the version reported at boot and in the info API; update
the HA manifest for an integration release. Preserve existing API compatibility
or document and test any deliberate migration.

Update the relevant README/API/setup instructions when behavior changes. Preserve
upstream attribution, `NOTICE`, and license files. The public distribution uses
GPL v3 and retains Apache-2.0 notices for applicable components; do not silently
remove notices or relicense imported code.

Summarize the behavior changed, checks performed, and remaining limitations.
Keep unrelated refactors out of focused changes. Do not deploy, publish, or create
release artifacts merely because a build passed; those actions need to be part
of the requested task.
