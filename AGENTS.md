# Agents

- The stack lives here; screen reading, actions and model clients live in the fork (pinned in `pyproject.toml`).
  Change the fork there, push, then bump the pin.
- Log every run and result in `private/docs/computer_use.md`: plain numbers, no pass/fail bars.
- Tests: `uv run pytest`.

- Secrets (2026-10-25): `.env` keeps settings only; `TYPESAFE_API_KEY=` stays blank. Run key-needing commands as `private/scripts/with-keys.sh CMD` (key from the fleet infra secrets). Never read or print key values.
