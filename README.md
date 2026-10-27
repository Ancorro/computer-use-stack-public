# computer-use-stack

Project page (runs, results, plans): https://claude.ai/artifact/KHW6GhQqVBNfcTz7tTVSei

Computer use in one loop. Each step a fast decision model picks the action from the numbered items on screen; when it
is unsure, or the action needs words (typing, done), a vision model sees the screenshot and picks it instead. The
earlier planner stack (`cu_stack/stack.py`: plan, step checks, re-plan, done-check) is retired.

Screen reading (OCR, optical character recognition, plus the accessibility tree), actions, the decision model client and
the writer client come from the fork [Ancorro/typesafe-computer-use](https://github.com/Ancorro/typesafe-computer-use),
pinned in `pyproject.toml`. This repo holds only the loop and the stack.

| Path | What |
|---|---|
| `cu_stack/loop.py`, `loop_agent.py` | the loop, and it as an OSWorld agent (`scripts/osworld run-loop`) |
| `cu_stack/stack.py` | the retired planner stack: plan, step, check, re-plan, done-check, fallback |
| `cu_stack/osworld_agent.py` | the stack as an OSWorld (desktop task benchmark) agent |
| `osworld_overlay/` | files the fork's `scripts/osworld setup` copies into OSWorld when `CU_STACK` points here |
| `scripts/desk-goal.ps1` | run a goal on this Windows desktop with the one loop (dry run unless `--act`) |
| `scripts/osworld-dev.sh` | the 14 runnable OSWorld dev tasks with the one loop, 2 VMs |

## Offline tests

`container/` runs the CPU tests with no network: `container/wheels/` holds the Linux x86_64 wheels for Python 3.12
(versions from `uv.lock`, without the OCR extra), and `container/run.sh` runs a command in bubblewrap with no
network when `bwrap` is available.

```
bash container/setup.sh                       # unpacks the wheels into .container/ (no pip, no venv)
bash container/run.sh python -m pytest -q     # 35 tests, a few seconds
```

`container/fetch.sh` refreshes the wheels (needs network and uv).

## Run

- This desktop: `scripts\desk-goal.ps1 'In Calculator, compute 24*60*60'`, then add `--act` to really click.
- OSWorld: in the fork, `CU_STACK=<this repo> scripts/osworld setup`, then `scripts/osworld run-stack TASK... --ocr rapidocr`.
- Models are set by environment (`.env`, git-ignored): `CLICKER_WRITER_API`, `CLICKER_WRITER_BASE_URL`,
  `CLICKER_WRITER_MODEL`, `CLICKER_ANSWER_MODEL` (planner and done-check), `TYPESAFE_*` (the decision model).
