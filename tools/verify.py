"""Offline build/tests only; never opens serial devices or real gateway services."""
from pathlib import Path
import subprocess
import sys
root = Path(__file__).resolve().parents[1]
def run(args):
    subprocess.run(args, cwd=root, check=True)
run([sys.executable, "-m", "platformio", "run", "--project-dir", "ttgo-io-gateway"])
run(["docker", "run", "--rm", "--network", "none", "--mount",
     f"type=bind,source={root / 'custom_components'},target=/work/custom_components,readonly",
     "--mount", f"type=bind,source={root / 'tests'},target=/work/tests,readonly",
     "--workdir", "/work", "--entrypoint", "python",
     "ghcr.io/home-assistant/home-assistant:2026.9.0", "-m", "unittest", "discover",
     "-s", "tests/somfy_io", "-p", "test_integration.py", "-v"])
run(["docker", "run", "--rm", "--network", "none", "--mount",
     f"type=bind,source={root / 'ttgo-io-gateway' / 'src'},target=/src,readonly",
     "--mount", f"type=bind,source={root / 'tests' / 'somfy_io'},target=/tests,readonly",
     "--entrypoint", "sh", "mcr.microsoft.com/devcontainers/python:3.12", "-c",
     "g++ -std=c++17 -Wall -Wextra -Werror -I/src /tests/test_policy.cpp -o /tmp/test && /tmp/test"])
