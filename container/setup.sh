#!/bin/bash
# Offline setup for the CPU tests: unpacks the wheels in container/wheels/ that match this Python into
# .container/site (no network, no pip, no venv). Needs Python 3.12 on x86_64 Linux (the wheels are cp312).
# The OCR extra (rapidocr) is not included, so real screen runs need `uv sync`.
#   bash container/setup.sh && bash container/run.sh python -m pytest -q
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd)
py=""
for c in python3 python3.12; do
  if command -v "$c" >/dev/null && "$c" -c 'import sys; sys.exit(sys.version_info[:2] != (3, 12))'; then
    py=$c; break
  fi
done
[ -n "$py" ] || { echo "needs Python 3.12; found: $(python3 --version 2>&1)" >&2; exit 1; }
rm -rf "$root/.container" && mkdir -p "$root/.container/site"
"$py" -I - "$root" <<'EOF'
import re, sys, zipfile
from pathlib import Path

root = Path(sys.argv[1])
site, wheels = root / ".container/site", root / "container/wheels"
tag = f"cp{sys.version_info.major}{sys.version_info.minor}"
want = {}
for line in (root / "container/requirements.txt").read_text().splitlines():
    if "==" in line and not line.startswith("#"):
        name, version = line.split("==")
        want[re.sub(r"[-_.]+", "_", name).lower()] = version
for name, version in sorted(want.items()):
    found = [w for w in wheels.glob("*.whl")
             if re.sub(r"[-_.]+", "_", w.name.split("-")[0]).lower() == name and w.name.split("-")[1] == version
             and (w.name.split("-")[2] in ("py3", tag) or w.name.split("-")[3] == "abi3")]
    if not found:
        sys.exit(f"no wheel for {name}=={version} on {tag}")
    zipfile.ZipFile(found[0]).extractall(site)
print(f"ready: Python {sys.version.split()[0]}, {len(want)} packages in .container/site")
EOF
echo "$py" > "$root/.container/python"
