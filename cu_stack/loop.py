"""One loop: a vision model sees the screen and picks one action, until it says done.

  goal -> [capture -> screen items + text -> model (screenshot + items) -> one action -> act] x N -> done / fail

No planner, step kinds, expected-text checks or hand-off (the stack in `stack.py`). The 2026-10-15 OSWorld test showed
those parts causing 18 of the stack's 40 failures, and the decision model between them mostly confirming typing.
The model gets the items the fork's perception finds (text recognition plus the accessibility tree), numbered, and
clicks by number; it can also type, press keys, scroll, wait, and end the run.

With a fast decision model (`LoopConfig.fast`, a TypeSafe/SubQ client), each step asks it first, through the fork's
`decide`: a concrete action at `fast_min` confidence or more (click an item, Enter, Escape, scroll, wait) is carried
out directly; anything else (typing, done, switching, low confidence, or a fast action that left the screen unchanged)
goes to the vision model as above. The vision model then picks the action itself, not a text hint for the fast model.

`run_loop` reads and acts through `platform_adapter.desktop`, so it drives this machine or an OSWorld VM
(`loop_agent.py`).

  python -m cu_stack.loop "<goal>" [--act] [--steps=30] [--fast]
Without --act: one capture and one decision, nothing clicked or typed. Log: runs/loop/<run>/loop.jsonl.
"""

from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass, field, replace
from pathlib import Path

from PIL import ImageChops, ImageStat

from typesafe_computer_use import config
from typesafe_computer_use.config import DEFAULT_MIN_CONFIDENCE, MAX_OPTIONS
from typesafe_computer_use.decide import decide as fast_decide
from typesafe_computer_use.models import Missed
from typesafe_computer_use.perception import OcrCache, capture, perceive
from typesafe_computer_use.platform_adapter import desktop
from typesafe_computer_use.writer import _structured, make_writer

MAX_STEPS = 50  # OSWorld's own action budget per task
HISTORY = 15  # past actions the model sees
CHANGE = 1.0  # mean absolute 8-bit difference on a small copy that counts as a changed screen

SYSTEM = """You operate a computer ({desktop}) to reach the user's goal, one action at a time.
Each turn you get a screenshot, the numbered items on screen (text and controls, with their role), the screen's other
text, the app in front, and your recent actions with whether the screen changed after each.

Pick exactly one action:
- click: click item number `item` (just the number, such as "12").
- double_click: double-click item number `item`.
- type: type `text` into whatever has focus. End it with a newline to press Enter.
- key: press `text`, one key or a combination such as ctrl+s, ctrl+shift+t, alt+f4, super, enter, tab, esc.
- scroll: scroll the window in front; `text` is "up" or "down".
- wait: something is loading.
- shell: run `text` as a bash command on the computer, out of sight; its output comes back to you as text next turn
  (`last_shell_output`). Surer than reading a terminal off the screen; nothing changes on screen.
- done: the goal is fully met, including any file saved where asked.
- fail: the goal is impossible on this computer. Say why in `note`.

Use whichever route is surest: the app's own controls, keyboard shortcuts, or a terminal. If an action left the
screen unchanged, do something different rather than repeat it. Nobody can answer questions: when a detail is missing,
take the most reasonable reading.

You see only this screen and your recent actions. Put anything you will need later (file contents, numbers, a format,
what you found or changed) in `remember`: it is kept and shown to you every turn as `notes`. Before `done`, check the
result the way the goal asks for it, in the app it names.{extra}"""

REPLY = {"note": {"type": "string"}, "remember": {"type": "string"}, "action": {"type": "string"}, "item": {"type": "string"}, "text": {"type": "string"}}  # item: a number, as text (the fork's reply check knows strings and flags)
# Room for the reply, and for the model's thinking where its endpoint counts that in too (Ollama does).
REPLY_TOKENS = int(os.environ.get("LOOP_MAX_TOKENS") or 1500)
SHELL_LINE = SYSTEM[SYSTEM.index("- shell:"):SYSTEM.index("- done:")]
ACTIONS = ("click", "double_click", "type", "key", "scroll", "wait", "shell", "done", "fail")
NOTES = 6000  # characters of `remember` notes kept, the newest
OUTPUT = 4000  # characters of a shell command's output shown, the last
REPEAT = 3  # the same action this many times in the recent ones gets a warning
# The fast model's kinds it may carry out alone, as the loop's own actions; every other kind goes to the vision model.
FAST = {"click_item": ("click", ""), "press_enter": ("key", "enter"), "press_escape": ("key", "esc"),
        "scroll_down": ("scroll", "down"), "scroll_up": ("scroll", "up"), "wait": ("wait", "")}


@dataclass
class LoopConfig:
    goal: str
    out: Path
    writer: object
    desktop_name: str = "Windows"
    act: bool = False
    max_steps: int = MAX_STEPS
    extra: str = ""  # desktop-specific hints for the prompt, such as GNOME's keys
    fast: object = None  # a TypeSafe client: the fast decision model asked first each step
    fast_min: float = DEFAULT_MIN_CONFIDENCE
    shell: object = None  # runs a bash command on the desktop and returns its output; None: no shell action


@dataclass
class LoopResult:
    result: str  # done / fail / steps / dry run
    note: str = ""
    steps: int = 0
    history: list[dict] = field(default_factory=list)


def _changed(a, b) -> bool:
    small = (160, 90)
    diff = ImageChops.difference(a.convert("L").resize(small), b.convert("L").resize(small))
    return ImageStat.Stat(diff).mean[0] > CHANGE


class Loop:
    def __init__(self, cfg: LoopConfig) -> None:
        self.cfg = cfg
        cfg.out.mkdir(parents=True, exist_ok=True)
        self.path = cfg.out / "loop.jsonl"

    def log(self, event: dict) -> None:
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"t": round(time.time(), 1), **event}, default=str) + "\n")

    def look(self):
        """One capture: the numbered items, plus text recognition's other lines and the focused field's value (in a
        terminal the field is the whole window, which the items leave out)."""
        screen = capture(browser=config.browser())
        cache = OcrCache()
        items = perceive(screen, MAX_OPTIONS, self.cfg.goal, cache=cache)
        seen = {it.text for it in items}
        other = [t for t, _, _ in cache.lines if t not in seen]
        if screen.field is not None and screen.field.value:
            other.append(screen.field.value[-2000:])
        return screen, items, other

    def decide(self, screen, items, other, history, notes="", output=None) -> dict:
        recent = history[-HISTORY:]
        seen = [(h["action"], h.get("item"), h.get("text")) for h in recent]
        repeats = sorted({f"{a} {i or ''} {t or ''}".strip()[:80] for a, i, t in seen if seen.count((a, i, t)) >= REPEAT})
        packet = {
            "goal": self.cfg.goal,
            "front_app": screen.app,
            "items": [f"[{it.index}] {it.role + ': ' if it.role else ''}{it.text}" for it in items],
            "other_text": other[:150],
            "recent_actions": recent,
            "notes": notes,
            **({"last_shell_output": output} if output is not None else {}),
            **({"warning": f"you are looping: repeated {repeats}. Use what you already learned (put it in remember)"
                           " and do the next step of the goal."} if repeats else {}),
        }
        system = (SYSTEM if self.cfg.shell else SYSTEM.replace(SHELL_LINE, "")).format(
            desktop=self.cfg.desktop_name, extra="\n\n" + self.cfg.extra if self.cfg.extra else "")
        reply = _structured(self.cfg.writer, system, packet, REPLY, max_tokens=REPLY_TOKENS, answering=True, image=screen.image)
        reply["action"] = str(reply.get("action", "")).strip().lower()
        digits = "".join(ch for ch in str(reply.get("item", "")) if ch.isdigit())
        reply["item"] = int(digits) if digits else None
        return reply

    def fast(self, screen, items, history) -> dict | None:
        """The fast model's action, or None to ask the vision model. Its last action leaving the screen unchanged
        sends this step to the vision model too."""
        if self.cfg.fast is None or (history and history[-1].get("by") == "fast" and not history[-1]["screen_changed"]):
            return None
        lines = [f"{h['action']} {h.get('item') or ''} {h.get('text') or ''}".strip() + f" -> {h['result']}"
                 for h in history]
        d = fast_decide(self.cfg.fast, self.cfg.goal, screen, items, lines, config.browser(), None)
        kind, conf = d.kind.choice, round(d.confidence, 2)
        mapped = FAST.get(kind)
        if mapped is None or conf < self.cfg.fast_min or (kind == "click_item" and d.item is None):
            return {"escalate": True, "fast_kind": kind, "fast_confidence": conf}
        action, text = mapped
        item = int(d.item.choice) if kind == "click_item" else None
        return {"action": action, "item": item, "text": text, "note": f"fast: {kind}", "fast_confidence": conf}

    def act(self, reply: dict, screen, items) -> str:
        """Carry out one action; returns what happened, for the history."""
        action, text = reply["action"], str(reply.get("text") or "")
        if action in ("click", "double_click"):
            item = next((it for it in items if it.index == reply.get("item")), None)
            if item is None:
                return f"no item {reply.get('item')} on screen"
            point = screen.to_points(item)
            desktop.click_at(point)
            if action == "double_click":
                desktop.click_at(point)
            return f"clicked [{item.index}] {item.text[:60]}"
        if action == "type":
            if not text:
                return "nothing to type"
            desktop.type_text(text)
            return "typed"
        if action == "key":
            keys = [k.strip() for k in text.lower().split("+") if k.strip()]
            if not keys:
                return "no key given"
            if len(keys) == 1:
                desktop.press(keys[0])
            elif hasattr(desktop, "hotkey"):
                desktop.hotkey(*keys)
            elif len(keys) == 2 and keys[0] == "ctrl":
                desktop.press(keys[1], command=True)
            else:
                return f"this desktop cannot press {text}"
            return "pressed"
        if action == "scroll":
            desktop.scroll(-5 if text.strip().lower() == "down" else 5)
            return "scrolled"
        if action == "wait":
            return "waited"
        if action == "shell":
            if self.cfg.shell is None or not text.strip():
                return "no shell here" if self.cfg.shell is None else "no command given"
            self.output = str(self.cfg.shell(text))[-OUTPUT:]
            return "ran; output in last_shell_output"
        return f"unknown action {action!r}"

    def run(self) -> LoopResult:
        cfg = self.cfg
        self.log({"event": "start", "goal": cfg.goal, "act": cfg.act, "max_steps": cfg.max_steps})
        history: list[dict] = []
        notes, self.output = "", None
        for i in range(1, cfg.max_steps + 1):
            desktop.check_abort()
            screen, items, other = self.look()
            t0 = time.time()
            fast = self.fast(screen, items, history)
            by = "fast" if fast and not fast.get("escalate") else "vision"
            reply = fast if by == "fast" else {**(fast or {}), **self.decide(screen, items, other, history, notes, self.output)}
            seconds = round(time.time() - t0, 1)
            action = reply["action"]
            if str(reply.get("remember") or "").strip():
                notes = (notes + "\n" + reply["remember"].strip()).strip()[-NOTES:]
            self.log({"event": "decide", "i": i, "by": by, "app": screen.app, "items": len(items), "seconds": seconds,
                      **reply})
            if action in ("done", "fail"):
                self.log({"event": "end", "result": action, "steps": i - 1, "note": reply.get("note", "")})
                return LoopResult(action, reply.get("note", ""), i - 1, history)
            if not cfg.act:
                self.log({"event": "end", "result": "dry run", "steps": 0})
                return LoopResult("dry run", reply.get("note", ""), 0, history)
            self.output = None if action != "shell" else self.output
            try:
                outcome = self.act(reply, screen, items) if action in ACTIONS else f"unknown action {action!r}"
            except (Missed, ValueError) as e:  # the desktop refused it (a cursor it may not move, a key it lacks)
                outcome = f"failed: {e}"
            desktop.sleep_watching(2.0 if action == "wait" else 0.8)
            after = desktop.screenshot()
            changed = _changed(screen.image, after)
            entry = {"step": i, "by": by, "action": action, "item": reply.get("item"), "text": reply.get("text", "")[:200],
                     "result": outcome, "screen_changed": changed}
            history.append(entry)
            self.log({"event": "act", **entry})
        self.log({"event": "end", "result": "steps", "steps": cfg.max_steps})
        return LoopResult("steps", "", cfg.max_steps, history)


def main(argv: list[str]) -> int:
    config.load_dotenv(Path.cwd() / ".env")
    args = [a for a in argv if not a.startswith("--")]
    flags = dict(a[2:].split("=", 1) if "=" in a else (a[2:], "1") for a in argv if a.startswith("--"))
    if not args:
        sys.exit(__doc__)
    writer = make_writer()
    if writer is None:
        sys.exit("no writer: set CLICKER_WRITER_API (claude-code / codex / opencode / openai) or a key in .env")
    out = Path("runs/loop") / time.strftime("%Y%m%d-%H%M%S")
    cfg = LoopConfig(goal=args[0], out=out, writer=writer, act="act" in flags, max_steps=int(flags.get("steps", 30)))
    if "fast" in flags:
        from typesafe_sdk import TypeSafeClient
        from typesafe_computer_use.calls import Calls, MeteredClassifier
        with TypeSafeClient() as client:  # metered: it answers SubQ's one-option choices locally (SubQ refuses them)
            res = Loop(replace(cfg, fast=MeteredClassifier(client, Calls()))).run()
    else:
        res = Loop(cfg).run()
    print(f"{res.result} after {res.steps} steps{': ' + res.note if res.note else ''}\nlog: {out / 'loop.jsonl'}")
    return 0 if res.result in ("done", "dry run") else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
