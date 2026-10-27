"""Generated computer-use tasks with checkers, as OSWorld task files.

Each template builds a task from a seed: random file names and contents, an instruction, a setup that writes the start
state into the VM, and a checker that reads the end state and prints PASS or FAIL. Setup and checker are Python run in
the VM (python3, base64 in the command, so no quoting). `size` sets how much there is to do (files, lines, rows).

    python -m cu_stack.gen_tasks OSWORLD_CHECKOUT --n 12 --seed 0     writes evaluation_examples/examples/gen/<id>.json
                                                                       and prints the task list for scripts/osworld
"""

from __future__ import annotations

import argparse
import base64
import json
import random
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

HOME = "/home/user"
WORDS = ("amber basil cedar delta ember fable garnet harbor iris juniper kestrel lumen maple nectar orbit pepper quartz"
         " raven saffron tundra umber velvet willow yarrow zephyr cobalt dune fern glacier hazel").split()


@dataclass
class Task:
    template: str
    size: int
    instruction: str
    setup: str            # Python run in the VM before the task: writes the start state under HOME
    check: str            # Python run in the VM after the task: prints PASS or FAIL
    solve: Callable[[str], None]  # what a correct run does, given HOME (tests only)


def _name(rng: random.Random, k: int = 2) -> str:
    return "_".join(rng.sample(WORDS, k))


def _files_code(files: dict[str, str]) -> str:
    """Python that writes these files (paths relative to HOME)."""
    return (f"import os\nH={HOME!r}\nfor p, s in {files!r}.items():\n"
            "    p = os.path.join(H, p); os.makedirs(os.path.dirname(p), exist_ok=True); open(p, 'w').write(s)\n")


def _check(body: str) -> str:
    return (f"import os\nH={HOME!r}\nD=os.path.join(H, 'Desktop')\ndef ok():\n"
            + "".join(f"    {line}\n" for line in body.strip().splitlines())
            + "try:\n    print('PASS' if ok() else 'FAIL')\nexcept Exception as e:\n    print('FAIL', e)\n")


def write_note(rng: random.Random, size: int) -> Task:
    name, phrase = _name(rng), " ".join(rng.sample(WORDS, size + 2))
    body = f"return open(os.path.join(D, {name + '.txt'!r})).read().strip() == {phrase!r}"
    def solve(h): Path(h, "Desktop", f"{name}.txt").write_text(phrase + "\n")
    return Task("write_note", size, f"Create a text file named {name}.txt on the Desktop that contains exactly this line: {phrase}",
                _files_code({"Desktop/.keep": ""}), _check(body), solve)


def rename(rng: random.Random, size: int) -> Task:
    a, b, text = _name(rng), _name(rng), " ".join(rng.choices(WORDS, k=6))
    body = (f"return not os.path.exists(os.path.join(D, {a + '.txt'!r})) and "
            f"open(os.path.join(D, {b + '.txt'!r})).read() == {text!r}")
    def solve(h): Path(h, "Desktop", f"{a}.txt").rename(Path(h, "Desktop", f"{b}.txt"))
    return Task("rename", size, f"Rename the file {a}.txt on the Desktop to {b}.txt.",
                _files_code({f"Desktop/{a}.txt": text}), _check(body), solve)


def sort_files(rng: random.Random, size: int) -> Task:
    names = rng.sample(WORDS, 2 * size)
    csvs, txts = [n + ".csv" for n in names[:size]], [n + ".txt" for n in names[size:]]
    folder = _name(rng)
    body = (f"F=os.path.join(D, {folder!r})\n"
            f"return sorted(os.listdir(F)) == {sorted(csvs)!r} and all(os.path.exists(os.path.join(D, t)) for t in {txts!r})")
    def solve(h):
        Path(h, "Desktop", folder).mkdir()
        for c in csvs: Path(h, "Desktop", c).rename(Path(h, "Desktop", folder, c))
    return Task("sort_files", size, f"Make a folder named {folder} on the Desktop and move every .csv file from the Desktop "
                "into it. Leave the other files where they are.",
                _files_code({f"Desktop/{f}": "x\n" for f in csvs + txts}), _check(body), solve)


def sum_numbers(rng: random.Random, size: int) -> Task:
    nums = [rng.randint(10, 999) for _ in range(size + 2)]
    body = "return open(os.path.join(D, 'answer.txt')).read().strip() == " + repr(str(sum(nums)))
    def solve(h): Path(h, "Desktop", "answer.txt").write_text(f"{sum(nums)}\n")
    return Task("sum_numbers", size, "The file numbers.txt on the Desktop has one number per line. Write their sum, "
                "just the number, into a new file answer.txt on the Desktop.",
                _files_code({"Desktop/numbers.txt": "".join(f"{n}\n" for n in nums)}), _check(body), solve)


def edit_lines(rng: random.Random, size: int) -> Task:
    items = rng.sample(WORDS, size + 3)
    lines, drop, add = items[:-1], items[rng.randrange(size + 2)], items[-1]
    want = [x for x in lines if x != drop] + [add]
    body = f"return [l.strip() for l in open(os.path.join(D, 'list.txt')).read().splitlines() if l.strip()] == {want!r}"
    def solve(h): Path(h, "Desktop", "list.txt").write_text("".join(f"{x}\n" for x in want))
    return Task("edit_lines", size, f"Open list.txt on the Desktop in the Text Editor, delete the line '{drop}', add a new last "
                f"line '{add}', and save it.",
                _files_code({"Desktop/list.txt": "".join(f"{x}\n" for x in lines)}), _check(body), solve)


def csv_total(rng: random.Random, size: int) -> Task:
    rows = [(w, rng.randint(1, 99)) for w in rng.sample(WORDS, size + 2)]
    total = sum(p for _, p in rows)
    body = ("import csv\nr = [x for x in csv.reader(open(os.path.join(D, 'prices.csv'))) if x]\n"
            f"return r[:-1] == {[['item', 'price']] + [[w, str(p)] for w, p in rows]!r} and r[-1][0] == 'total' "
            f"and float(r[-1][1]) == {total}")
    def solve(h): Path(h, "Desktop", "prices.csv").write_text(
        "item,price\n" + "".join(f"{w},{p}\n" for w, p in rows) + f"total,{total}\n")
    return Task("csv_total", size, "Open prices.csv on the Desktop in LibreOffice Calc. Add a last row with 'total' in the "
                "item column and the sum of all prices in the price column, then save it, keeping the CSV format.",
                _files_code({"Desktop/prices.csv": "item,price\n" + "".join(f"{w},{p}\n" for w, p in rows)}),
                _check(body), solve)


TEMPLATES = {f.__name__: f for f in (write_note, rename, sort_files, sum_numbers, edit_lines, csv_total)}


def generate(n: int, seed: int, sizes=(1, 3, 5)) -> list[tuple[str, Task]]:
    """n tasks, cycling templates and sizes; the same seed gives the same tasks and ids."""
    out = []
    for i in range(n):
        tname = list(TEMPLATES)[i % len(TEMPLATES)]
        size = sizes[(i // len(TEMPLATES)) % len(sizes)]
        out.append((str(uuid.uuid5(uuid.NAMESPACE_URL, f"cu-gen/{seed}/{i}/{tname}/{size}")),
                    TEMPLATES[tname](random.Random(f"{seed}/{i}"), size)))
    return out


def _py(code: str) -> str:
    return f"echo {base64.b64encode(code.encode()).decode()} | base64 -d | python3"


def osworld_json(tid: str, t: Task) -> dict:
    return {
        "id": tid, "snapshot": "os", "instruction": t.instruction, "source": f"cu_stack.gen_tasks/{t.template}/{t.size}",
        "config": [{"type": "execute", "parameters": {"command": _py(t.setup), "shell": True}}],
        "related_apps": ["os"],
        "evaluator": {"func": "check_include_exclude",
                      "result": {"type": "vm_command_line", "command": _py(t.check), "shell": True},
                      "expected": {"type": "rule", "rules": {"include": ["PASS"], "exclude": ["FAIL"]}}},
        "proxy": False, "fixed_ip": False, "possibility_of_env_change": "low",
    }


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("checkout", type=Path, help="the OSWorld checkout (fork's .osworld/OSWorld-V2)")
    ap.add_argument("--n", type=int, default=12)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--sizes", default="1,3,5")
    a = ap.parse_args(argv)
    d = a.checkout / "evaluation_examples" / "examples" / "gen"
    d.mkdir(parents=True, exist_ok=True)
    tasks = generate(a.n, a.seed, tuple(int(s) for s in a.sizes.split(",")))
    for tid, t in tasks:
        (d / f"{tid}.json").write_text(json.dumps(osworld_json(tid, t), indent=2))
    print(" ".join(f"gen/{tid}" for tid, _ in tasks))


if __name__ == "__main__":
    main()
