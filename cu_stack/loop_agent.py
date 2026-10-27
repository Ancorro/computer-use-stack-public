"""The one loop (`cu_stack/loop.py`) as an OSWorld agent: one model sees the screen and picks each action.

Everything `JevAgent` does stays: the worker thread, the queues to `predict`, the VM as the desktop through
`OSWorldDesktop`, the light tree fetch and the run record. The worker runs `Loop.run` instead of `runner.run`; every
action counts against OSWorld's step budget. "fail" ends with `FAIL`, OSWorld's claim that the task is infeasible;
every other end is `DONE`, scored by OSWorld's check. Results go to `<task result folder>/loop/`. `LOOP_FAST=1` asks the
fast decision model (TypeSafe/SubQ, from `TYPESAFE_*`) first each step; `LOOP_FAST_MIN` sets its confidence floor.
`LOOP_SHELL=1` gives the loop its shell action: bash on the VM, output back as text.
"""

from __future__ import annotations

import os
from dataclasses import replace
from contextlib import nullcontext
from functools import partial

from typesafe_sdk import TypeSafeClient

from typesafe_computer_use.calls import Calls, MeteredClassifier
from typesafe_computer_use.models import Abort
from typesafe_computer_use.osworld import tree
from typesafe_computer_use.osworld.agent import DONE, JevAgent, _Failed, _Run, _Step
from typesafe_computer_use.osworld.desktop import OSWorldDesktop
from typesafe_computer_use.platform_adapter import using

from cu_stack import gemma_decider
from cu_stack.loop import Loop, LoopConfig
from cu_stack.stack import GNOME_KEYS

FAIL = "FAIL"
RUN_FOLDER = "loop"


SHELL_SECONDS = 60
SHELL_SCRIPT = """import subprocess
r = subprocess.run(["bash", "-lc", {cmd!r}], capture_output=True, text=True, timeout={t}, cwd="/home/user")
print(r.stdout + r.stderr + ("" if r.returncode == 0 else f"[exit {{r.returncode}}]"))
"""


def _shell(controller, command: str) -> str:
    """The loop's shell action on the VM: a bash command through OSWorld's Python runner (the same route as the tree
    walk), its output and errors as text. Not an OSWorld step: no input, nothing on screen."""
    try:
        reply = controller().run_python_script(SHELL_SCRIPT.format(cmd=command, t=SHELL_SECONDS),
                                               timeout=SHELL_SECONDS + 10)
    except Exception as error:
        return f"the command could not run: {error!r}"
    if not isinstance(reply, dict):
        return f"no reply: {reply!r}"
    if reply.get("status") != "success":
        return f"failed: {reply.get('error') or reply.get('message')}"
    return reply.get("output") or "(no output)"


class LoopAgent(JevAgent):
    def predict(self, instruction: str, obs: dict) -> tuple[str, list[str]]:
        if self._run is None:
            self._run = _LoopRun(self, instruction, self._stale)
            self._stale = None
        return self._run.predict(obs)


class _LoopRun(_Run):
    def __init__(self, agent: LoopAgent, instruction: str, after) -> None:
        super().__init__(agent, instruction, after)
        self.cfg = replace(self.cfg, out=agent.out_root / RUN_FOLDER)

    def _work(self, obs: dict) -> None:
        message: _Step | _Failed
        try:
            if self.after is not None:
                self.after.join()
            fetch = None
            if self.agent.controller is not None:
                check = tree.checking()
                fetch = partial(tree.fetch, self.agent.controller(), check=check)
                self.tree = tree.LIGHT_CHECKED if check else tree.LIGHT
            save = self.cfg.out if os.environ.get("JEV_OSWORLD_SAVE_A11Y") == "1" else None
            adapter = self.adapter = OSWorldDesktop(
                obs, self.agent.recognize_text, self._next_obs, fetch_tree=fetch, save_a11y=save
            )
            end = DONE
            fast = os.environ.get("LOOP_FAST")  # "1": SubQ/TypeSafe decides first; "gemma": the writer's Gemma does
            gemma = fast == "gemma"
            with using(adapter), (TypeSafeClient() if fast == "1" else nullcontext()) as client:
                loop = Loop(LoopConfig(goal=self.cfg.goal, out=self.cfg.out, writer=self.agent.writer,
                                       desktop_name="Ubuntu, an OSWorld virtual machine", act=True,
                                       max_steps=self.agent.max_steps, extra=GNOME_KEYS,
                                       shell=(partial(_shell, self.agent.controller)
                                              if self.agent.controller and os.environ.get("LOOP_SHELL") == "1"
                                              else None),
                                       fast=(gemma_decider.from_env() if gemma
                                             else client and MeteredClassifier(client, Calls())),
                                       **({"fast_min": float(os.environ["LOOP_FAST_MIN"])}
                                          if os.environ.get("LOOP_FAST_MIN") else {})))
                try:
                    result = loop.run()
                    ended = f"loop ended: {result.result}"
                    if result.result == "fail":
                        end, ended = FAIL, f"{ended}: {result.note}"
                except Abort as e:  # OSWorld's step limit, or a reset
                    loop.log({"event": "end", "result": f"aborted ({e})"})
                    ended = f"loop ended: aborted ({e})"
            final = [*self.final, *adapter.actions]
            message = _Step(ended, [*final, end], last=True)
        except BaseException as error:
            message = _Failed(error)
        self.to_predict.put(message)


__all__ = ["LoopAgent"]
