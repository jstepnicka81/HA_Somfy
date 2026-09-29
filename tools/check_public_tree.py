"""Check publishable files; report paths only, never secret values."""
from pathlib import Path
import re
import subprocess

root = Path(__file__).resolve().parents[1]
paths = subprocess.check_output(
    ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"], cwd=root
).decode().split("\0")
patterns = {
    "private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "JWT": re.compile(r"eyJ[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{12,}"),
    "private IP": re.compile(r"\b(?:192\.168\.\d{1,3}\.\d{1,3}|10\.\d{1,3}\.\d{1,3}\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3})\b"),
}
failures = []
for name in sorted(set(paths)):
    if not name:
        continue
    p = root / name
    if p.suffix.lower() in {".bin", ".cu8", ".iq", ".pfx", ".p12", ".key"} or "private" in p.relative_to(root).parts:
        failures.append((name, "excluded file type"))
        continue
    try:
        text = p.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        failures.append((name, "unexpected binary"))
        continue
    for label, pattern in patterns.items():
        if pattern.search(text):
            failures.append((name, label))
for name, label in failures:
    print(f"FAIL {name}: {label}")
if failures:
    raise SystemExit(1)
print("Public-tree checks passed. Review staged changes before publishing; pattern checks are not a guarantee.")
