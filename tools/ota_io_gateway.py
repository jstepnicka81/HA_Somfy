"""Upload an application image to an authenticated ESP gateway (no RF commands)."""
import argparse
import hashlib
import ipaddress
import json
from pathlib import Path
import secrets
import urllib.error
import urllib.request


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', required=True, type=ipaddress.IPv4Address)
    parser.add_argument('--config', required=True, type=Path, help='Private JSON containing token')
    parser.add_argument('--firmware', required=True, type=Path)
    args = parser.parse_args()
    token = json.loads(args.config.read_text(encoding='utf-8-sig'))['token']
    data = args.firmware.read_bytes()
    if not data or data[0] != 0xE9:
        parser.error('Expected an ESP application firmware.bin, not a complete flash backup')
    boundary = 'somfy-' + secrets.token_hex(16)
    body = (f'--{boundary}\r\nContent-Disposition: form-data; name="firmware"; '
            'filename="firmware.bin"\r\nContent-Type: application/octet-stream\r\n\r\n').encode()
    body += data + f'\r\n--{boundary}--\r\n'.encode()
    request = urllib.request.Request(f'http://{args.host}/api/v1/ota', data=body, method='POST', headers={
        'Authorization': 'Bearer ' + token,
        'Content-Type': f'multipart/form-data; boundary={boundary}',
        'X-Firmware-Size': str(len(data)),
        'X-Firmware-SHA256': hashlib.sha256(data).hexdigest(),
    })
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    try:
        with opener.open(request, timeout=90) as response:
            result = json.load(response)
    except urllib.error.HTTPError as err:
        raise SystemExit(f'OTA rejected (HTTP {err.code}); no automatic retry.') from None
    except (OSError, ValueError):
        raise SystemExit('OTA acknowledgement uncertain. Check ESP version before retrying.') from None
    if result.get('result') != 'updated_restart_pending':
        raise SystemExit('Unexpected OTA response; check ESP before retrying.')
    print('Firmware accepted, checksum verified. ESP is restarting; verify /api/v1/info.')


if __name__ == '__main__':
    main()
