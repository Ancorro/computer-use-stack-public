import json
import subprocess
import sys

import pytest

import cu_stack.gen_tasks as gen


def run_py(code, home):
    """Run a task's VM-side Python here, with HOME pointed at a temp folder."""
    return subprocess.run([sys.executable, "-c", code.replace(repr(gen.HOME), repr(str(home)))],
                          capture_output=True, text=True, check=True).stdout


@pytest.mark.parametrize("tid,task", gen.generate(18, seed=7), ids=lambda x: getattr(x, "template", ""))
def test_checker_fails_at_start_and_passes_when_solved(tmp_path, tid, task):
    run_py(task.setup, tmp_path)
    assert run_py(task.check, tmp_path).startswith("FAIL")
    task.solve(str(tmp_path))
    assert run_py(task.check, tmp_path).strip() == "PASS"


def test_same_seed_same_tasks_and_every_template_used():
    a, b = gen.generate(12, seed=3), gen.generate(12, seed=3)
    assert [(i, t.instruction) for i, t in a] == [(i, t.instruction) for i, t in b]
    assert {t.template for _, t in a} == set(gen.TEMPLATES)
    assert gen.generate(12, seed=4)[0][1].instruction != a[0][1].instruction


def test_osworld_json_writes_setup_and_checker(tmp_path, capsys):
    gen.main([str(tmp_path), "--n", "6", "--seed", "1"])
    listed = capsys.readouterr().out.split()
    files = sorted((tmp_path / "evaluation_examples/examples/gen").glob("*.json"))
    assert len(files) == 6 and sorted(f"gen/{f.stem}" for f in files) == sorted(listed)
    j = json.loads(files[0].read_text())
    assert j["evaluator"]["result"]["command"].endswith("| base64 -d | python3")
    assert j["evaluator"]["expected"]["rules"] == {"include": ["PASS"], "exclude": ["FAIL"]}
