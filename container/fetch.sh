#!/bin/bash
# Refresh container/wheels/ and container/requirements.txt (needs network; run on Linux x86_64 with uv).
# The set is the CPU test environment only: the fork without its rapidocr extra, plus pytest. Real OSWorld runs use
# uv.lock instead. container/setup.sh installs these wheels with no network.
#   bash container/fetch.sh
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
fork="typesafe-computer-use @ git+https://github.com/Ancorro/typesafe-computer-use@c48c58e92f0ec9b42a27700419a844ae11d14f30"
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

printf '%s\npytest==9.1.1\n' "$fork" > "$work/in.txt"
# Same versions as uv.lock.
(cd "$here/.." && uv export --frozen --no-hashes --no-emit-project --no-header --no-annotate) \
  | grep -E '^[A-Za-z0-9_.-]+==' | sed 's/ *;.*//' > "$work/lock.txt"
uv pip compile "$work/in.txt" -q --no-header --no-annotate --python-version 3.12 \
  --python-platform x86_64-manylinux_2_28 -c "$work/lock.txt" -o "$work/req.txt"
grep -v '^typesafe-computer-use' "$work/req.txt" > "$work/pypi.txt"

rm -rf "$here/wheels" && mkdir -p "$here/wheels"
uv tool run --from pip==26.1 pip wheel -q --no-deps -w "$here/wheels" "${fork#*@ }"
for v in 3.12; do
  uv tool run --from pip==26.1 pip download -q --only-binary=:all: --no-deps --python-version "$v" \
    --platform manylinux_2_28_x86_64 --platform manylinux_2_17_x86_64 --platform manylinux2014_x86_64 \
    -d "$here/wheels" -r "$work/pypi.txt"
done
{ echo "# CPU test environment for container/setup.sh (written by container/fetch.sh; no OCR extra)."
  echo "typesafe-computer-use==0.2.0"; cat "$work/pypi.txt"; } > "$here/requirements.txt"
echo "$(ls "$here/wheels" | wc -l) wheels, $(du -sh "$here/wheels" | cut -f1)"
