"""Gemma 4 12B as the fast decision model, in place of SubQ Snap: the `system_one` call the fork's `decide` makes,
served on vLLM (a Slurm job kept out of the public copy): Ollama 0.32 returns log-probabilities for the first token only.

Like SubQ, one request per step: every question goes in one prompt and Gemma answers them in one short reply, one line
each (`kind: C`, `item: 41`), the screen state read once. Questions with up to 26 options are lettered A, B, ...; each
option's probability is its letter's share of the top-20 token probabilities at that answer. More options (on-screen
items, up to 255) are numbered; the answer's confidence is the probability of its digit tokens. Letter scoring follows
rlRobots `so101/deciders.py` GemmaLetter (owner 2026-10-21: one model for writing and deciding, untrained first).
"""

from __future__ import annotations

import json
import math
import os
import re
from types import SimpleNamespace

import httpx
from typesafe_sdk import ChoiceAnswer

LETTERS = 26


def _lettered(keys: list[str]) -> bool:
    return len(keys) <= LETTERS


def _label(keys: list[str], i: int) -> str:
    return chr(65 + i) if _lettered(keys) else str(i + 1)


def _prompt(state: dict, asked: dict[str, tuple]) -> str:
    parts = [json.dumps(state, ensure_ascii=False, default=str)]
    for name, (q, keys) in asked.items():
        opts = "\n".join(f"{_label(keys, i)}) {q.criteria[k]}" for i, k in enumerate(keys))
        parts.append(f"Question `{name}`: {q.instructions}\nOptions:\n{opts}")
    form = "\n".join(f"{name}: <{'letter' if _lettered(keys) else 'number'}>" for name, (_, keys) in asked.items())
    parts.append(f"Answer every question, one line each, with the letter or number of the best option only:\n{form}")
    return "\n\n".join(parts)


class GemmaDecider:
    """Answers `system_one(state=..., questions=...)` like a TypeSafe client. `misses` counts questions with no usable
    answer in the reply (the first option is then chosen at confidence 0)."""

    def __init__(self, base_url: str, model: str):
        self.url = base_url.rstrip("/").removesuffix("/v1") + "/v1/chat/completions"
        self.model, self.http = model, httpx.Client(timeout=120)
        self.misses = 0

    def _generate(self, prompt: str, tokens: int) -> list[dict]:
        """The reply's tokens, each with its log-probability and top 20 alternatives (OpenAI chat format)."""
        r = self.http.post(self.url, json=dict(
            model=self.model, temperature=0, max_tokens=tokens, logprobs=True, top_logprobs=20,
            messages=[{"role": "user", "content": prompt}]))
        r.raise_for_status()
        return (r.json()["choices"][0].get("logprobs") or {}).get("content") or []

    def _miss(self, keys) -> ChoiceAnswer:
        self.misses += 1
        return ChoiceAnswer(choice=keys[0], confidence=0.0, probabilities={k: 0.0 for k in keys})

    @staticmethod
    def _letter(token: dict, keys) -> ChoiceAnswer | None:
        letters = [chr(65 + i) for i in range(len(keys))]
        top: dict[str, float] = {}
        for t in token.get("top_logprobs") or []:
            k = t["token"].strip().strip("()*.<>").upper()
            if k in letters:
                top[k] = top.get(k, 0.0) + math.exp(t["logprob"])
        if not top:
            return None
        z = sum(top.values())
        p = {key: top.get(c, 0.0) / z for c, key in zip(letters, keys)}
        best = max(p, key=p.get)
        return ChoiceAnswer(choice=best, confidence=p[best], probabilities=p)

    @staticmethod
    def _number(tokens: list[dict], keys) -> ChoiceAnswer | None:
        digits = "".join(t["token"].strip() for t in tokens)
        if not digits or not 1 <= int(digits) <= len(keys):
            return None
        best, conf = keys[int(digits) - 1], math.exp(sum(t["logprob"] for t in tokens))
        return ChoiceAnswer(choice=best, confidence=conf, probabilities={best: conf})

    def _read(self, reply: list[dict], asked: dict[str, tuple]) -> dict[str, ChoiceAnswer]:
        """Walk the reply's tokens: after `name:` the next token is a letter answer, or the next run of digit tokens
        is a number answer."""
        names, out, line = list(asked), {}, ""
        i = 0
        while i < len(reply):
            open_q = re.search(r"(\w+):\s*$", line)
            name = open_q and open_q.group(1)
            text = reply[i]["token"]
            if name in asked and name not in out and text.strip():
                keys = asked[name][1]
                if _lettered(keys):
                    out[name] = self._letter(reply[i], keys)
                    i += 1
                else:
                    j = i
                    while j < len(reply) and re.fullmatch(r"\s*\d+", reply[j]["token"]):
                        j += 1
                    out[name] = self._number(reply[i:j], keys)
                    i = max(j, i + 1)
                line = ""
                continue
            line = (line + text).rsplit("\n", 1)[-1]
            i += 1
        return {n: out.get(n) or self._miss(asked[n][1]) for n in names}

    def system_one(self, state: dict, questions: dict, **_):
        answers, asked = {}, {}
        for name, q in questions.items():
            keys = list(q.criteria)
            if len(keys) == 1:
                answers[name] = ChoiceAnswer(choice=keys[0], confidence=1.0, probabilities={keys[0]: 1.0})
            else:
                asked[name] = (q, keys)
        if asked:
            reply = self._generate(_prompt(state, asked), 8 * len(asked) + 8)
            answers.update(self._read(reply, asked))
        return SimpleNamespace(answers=answers, model=f"gemma-decider:{self.model}")


def from_env() -> GemmaDecider:
    """The decider's server (LOOP_DECIDER_URL, LOOP_DECIDER_MODEL), by default the writer's own."""
    return GemmaDecider(os.environ.get("LOOP_DECIDER_URL") or os.environ["CLICKER_WRITER_BASE_URL"],
                        os.environ.get("LOOP_DECIDER_MODEL") or os.environ["CLICKER_WRITER_MODEL"])
