#!/bin/bash
# The 14 runnable OSWorld dev tasks with this repo's one loop, 2 VMs, on a Linux box where the fork's OSWorld is set up
# (FORK, default ~/src/typesafe-computer-use; keys in the fork's .env or the environment).
#   scripts/osworld-dev.sh [NAME]
# 0c825995 is left out: it needs Google Drive secrets, so it never runs.
set -euo pipefail
here=$(cd "$(dirname "$0")/.." && pwd)
cd "${FORK:-$HOME/src/typesafe-computer-use}"
mapfile -t tasks < <(python3 -c "import json; [print('multi_apps/' + t) for t in json.load(open('benchmarks/osworld/stack-prereg.json'))['dev'] if not t.startswith('0c825995')]")
export CU_STACK=$here PYTHONPATH=$here LOOP_NAME=${1:-loop-dev} LOOP_FAST=1 \
  CLICKER_WRITER_API=claude-code CLICKER_ANSWER_MODEL=opus CLICKER_ANSWER_REASONING=medium
scripts/osworld run-loop "${tasks[@]}" --ocr rapidocr --envs 2
