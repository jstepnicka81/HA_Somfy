# API and runtime behavior

The ESP exposes HTTP port 80 with bearer-token authentication on every
functional endpoint. API version: 1.

| Method | Path | Purpose |
|---|---|---|
| GET | /api/v1/info | Firmware version, ESP/radio identity, flags and assigned devices |
| GET | /api/v1/states | Cached feedback; GET itself does not transmit radio commands |
| PUT | /api/v1/devices | Complete assignment list, up to 32 devices |
| POST | /api/v1/command | position, tilt or stop; 32-hex-character request_id |
| POST | /api/v1/ota | Multipart firmware; X-Firmware-Size and X-Firmware-SHA256 |

Commands contain `id`, `action` and `request_id`. The position and tilt actions
also take an integer `position` from 0 to 100. For height, 100 means fully open.
Tilt follows the TaHoma percentage scale. HTTP 202 confirms acceptance, not
completed movement. Do not automatically replay an uncertain movement command.

Protect the API token and local network: HTTP and NVS are not encrypted, and
an OTA SHA-256 checksum does not replace an author signature.

State fields include `position`, `tilt_position`, `tilt_supported`, `available`,
`last_result` and `rssi_dbm`. RSSI is measured at the assigned ESP when it receives
a CRC-valid reply from that motor. It is neither Wi-Fi RSSI nor signal strength
measured at the motor. A valid challenge can provide RSSI even if the subsequent
position query fails. Each axis and RSSI independently expire after 120 seconds
without fresh data. A commanded target is never presented as actual feedback.

HA reads the cache every 5 seconds. The ESP normally queries each axis about
once every 30 seconds; blinds alternate height and tilt queries. After a local
movement command, polling temporarily becomes more frequent. The queue holds
eight entries and treats height and tilt separately. A new queued target
replaces the previous target for that motor/axis. STOP cancels both queued axes
for its motor. Queued commands expire after 5 seconds. The queue and duplicate
request cache live in RAM; reboot does not replay commands. One HA installation
manages ownership; automatic gateway failover is not implemented.

Tests use synthetic or anonymized values. The included Overkiz root CA contains
no private key. Owners import their own io system key over USB. The public
firmware does not include the original key-transfer receiver or key-export path.
