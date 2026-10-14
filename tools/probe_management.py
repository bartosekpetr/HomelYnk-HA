"""Probe the Wiser for KNX management API and take a test backup.

Usage (from the repository root):
    py -3 tools/probe_management.py 192.168.0.104

Read-only except for creating backup files locally; nothing is changed on the
controller. Credentials and the backup password are prompted for, never stored.
Output files (git-ignored, PRIVATE): wiser_backup_*.bin, wiser_mgmt_probe.json
"""

from __future__ import annotations

import base64
import getpass
import json
import re
import ssl
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASE = "/api/management/v1"
BACKUPS = {
    "flashsys": "/flashsys/system/backupConfiguration",
    "scada": "/scada-main/general/backup",
}
SAFE_GETS = ("/custom/deviceInfo", "/flashsys/Status/SystemStatus")


def password_ok(pwd: str) -> bool:
    """Controller rule: 8+ chars with an uppercase letter, a lowercase letter and a digit."""
    return (
        len(pwd) >= 8
        and re.search(r"[A-Z]", pwd) is not None
        and re.search(r"[a-z]", pwd) is not None
        and re.search(r"\d", pwd) is not None
    )


def request(host: str, auth: str, path: str, body: dict | None = None):
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    # The controller is on the LAN; bypass any corporate proxy.
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}), urllib.request.HTTPSHandler(context=ctx)
    )
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        f"https://{host}{BASE}{path}",
        data=data,
        method="POST" if body is not None else "GET",
        headers={
            "Authorization": f"Basic {auth}",
            "Accept": "application/json, application/octet-stream, */*",
            "Content-Type": "application/json",
        },
    )
    with opener.open(req, timeout=120) as resp:
        return resp.status, dict(resp.headers), resp.read()


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 1
    host = sys.argv[1]
    user = input("Username: ")
    auth = base64.b64encode(f"{user}:{getpass.getpass('Password: ')}".encode()).decode()

    probe: dict = {}
    for path in SAFE_GETS:
        try:
            status, _, body = request(host, auth, path)
            probe[path] = {"status": status, "body": json.loads(body)}
            print(f"GET {path}: HTTP {status}")
        except urllib.error.HTTPError as err:
            probe[path] = {"status": err.code}
            print(f"GET {path}: HTTP {err.code}")
        except Exception as err:  # noqa: BLE001
            probe[path] = {"error": str(err)}
            print(f"GET {path}: {err}")

    pwd = getpass.getpass("Backup password (8+ chars, upper, lower, digit): ")
    if not password_ok(pwd):
        print("Password does not meet the controller requirements.")
        return 1

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    for name, path in BACKUPS.items():
        try:
            status, headers, body = request(host, auth, path, {"data": {"password": pwd}})
            out = ROOT / f"wiser_backup_{name}_{stamp}.bin"
            out.write_bytes(body)
            probe[path] = {
                "status": status,
                "content_type": headers.get("Content-Type"),
                "disposition": headers.get("Content-Disposition"),
                "bytes": len(body),
                "magic": body[:4].hex(),
            }
            print(f"POST {path}: HTTP {status}, {len(body)} bytes -> {out.name}")
        except urllib.error.HTTPError as err:
            detail = err.read()[:300].decode(errors="replace")
            probe[path] = {"status": err.code, "detail": detail}
            print(f"POST {path}: HTTP {err.code} {detail}")
        except Exception as err:  # noqa: BLE001
            probe[path] = {"error": str(err)}
            print(f"POST {path}: {err}")

    (ROOT / "wiser_mgmt_probe.json").write_text(json.dumps(probe, indent=2), encoding="utf-8")
    print("\nWrote wiser_mgmt_probe.json. Keep it and the .bin files private.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
