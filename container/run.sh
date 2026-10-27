#!/bin/bash
# Run one command in the offline test environment (after container/setup.sh), inside bubblewrap with no network:
# the filesystem is read-only except this repo and a fresh /tmp. `python` in the command is the setup's Python.
# Where bwrap can't start (nested sandboxes often block user namespaces), the command runs directly.
#   bash container/run.sh python -m pytest -q
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd)
[ -f "$root/.container/python" ] || { echo "run container/setup.sh first" >&2; exit 1; }
mkdir -p "$root/.container/bin"
ln -sf "$(command -v "$(cat "$root/.container/python")")" "$root/.container/bin/python"
export PATH="$root/.container/bin:$PATH" PYTHONPATH="$root:$root/.container/site" PYTHONDONTWRITEBYTECODE=1
cd "$root"
if command -v bwrap >/dev/null && bwrap --ro-bind / / --unshare-net true 2>/dev/null; then
  exec bwrap --ro-bind / / --dev /dev --proc /proc --tmpfs /tmp --bind "$root" "$root" --chdir "$root" \
    --unshare-net --unshare-pid --die-with-parent "$@"
fi
echo "bwrap unavailable here; running without it" >&2
exec "$@"
