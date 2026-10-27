from types import SimpleNamespace

from PIL import Image

import cu_stack.loop as loop_mod
from cu_stack.loop import Loop, LoopConfig


class FakeDesktop:
    def __init__(self):
        self.done = []

    def check_abort(self): pass
    def sleep_watching(self, s): pass
    def screenshot(self): return Image.new("RGB", (160, 90), (len(self.done) * 40 % 255, 0, 0))
    def click_at(self, p): self.done.append(("click", p))
    def type_text(self, t): self.done.append(("type", t))
    def press(self, k, command=False): self.done.append(("press", k, command))
    def hotkey(self, *k): self.done.append(("hotkey", k))
    def scroll(self, n): self.done.append(("scroll", n))


def run(tmp_path, monkeypatch, replies):
    fake = FakeDesktop()
    item = SimpleNamespace(index=3, text="Save", role="button")
    screen = SimpleNamespace(image=Image.new("RGB", (160, 90)), app="gedit", to_points=lambda it: (10.0, 20.0))
    monkeypatch.setattr(loop_mod, "desktop", fake)
    lp = Loop(LoopConfig(goal="g", out=tmp_path, writer=None, act=True, max_steps=10))
    monkeypatch.setattr(lp, "look", lambda: (screen, [item], []))
    it = iter(replies)
    monkeypatch.setattr(lp, "decide", lambda *a: dict(next(it)))
    return lp.run(), fake


def test_actions_map_to_the_desktop_and_done_ends(tmp_path, monkeypatch):
    res, fake = run(tmp_path, monkeypatch, [
        {"action": "click", "item": 3}, {"action": "type", "text": "ls\n"}, {"action": "key", "text": "ctrl+s"},
        {"action": "key", "text": "ctrl+shift+t"}, {"action": "done", "note": "saved"}])
    assert res.result == "done" and res.steps == 4
    assert fake.done == [("click", (10.0, 20.0)), ("type", "ls\n"), ("hotkey", ("ctrl", "s")),
                         ("hotkey", ("ctrl", "shift", "t"))]


def test_a_missing_item_is_reported_not_clicked(tmp_path, monkeypatch):
    res, fake = run(tmp_path, monkeypatch, [{"action": "click", "item": 9}, {"action": "fail", "note": "no"}])
    assert res.result == "fail" and fake.done == []
    assert res.history[0]["result"] == "no item 9 on screen"


def ans(choice, confidence=0.9):
    return SimpleNamespace(choice=choice, confidence=confidence)


def fast_run(tmp_path, monkeypatch, decisions, vision):
    fake = FakeDesktop()
    item = SimpleNamespace(index=3, text="Save", role="button")
    screen = SimpleNamespace(image=Image.new("RGB", (160, 90)), app="gedit", to_points=lambda it: (10.0, 20.0))
    monkeypatch.setattr(loop_mod, "desktop", fake)
    lp = Loop(LoopConfig(goal="g", out=tmp_path, writer=None, act=True, max_steps=10, fast=object()))
    monkeypatch.setattr(lp, "look", lambda: (screen, [item], []))
    d, v = iter(decisions), iter(vision)
    monkeypatch.setattr(loop_mod, "fast_decide", lambda *a: next(d))
    monkeypatch.setattr(lp, "decide", lambda *a: dict(next(v)))
    return lp.run(), fake


def dec(kind, conf=0.9, item=None):
    return SimpleNamespace(kind=ans(kind, conf), item=ans(item) if item else None, confidence=conf)


def test_fast_model_acts_alone_when_confident_and_concrete(tmp_path, monkeypatch):
    res, fake = fast_run(tmp_path, monkeypatch, [dec("click_item", item="3"), dec("press_enter"), dec("done")],
                         [{"action": "done", "note": "ok"}])
    assert res.result == "done" and fake.done == [("click", (10.0, 20.0)), ("press", "enter", False)]
    assert [h["by"] for h in res.history] == ["fast", "fast"]


def test_low_confidence_and_typing_go_to_the_vision_model(tmp_path, monkeypatch):
    res, fake = fast_run(tmp_path, monkeypatch, [dec("click_item", 0.2, item="3"), dec("type_text"), dec("done")],
                         [{"action": "key", "text": "ctrl+s"}, {"action": "type", "text": "hi\n"}, {"action": "done"}])
    assert [h["by"] for h in res.history] == ["vision", "vision"]
    assert fake.done == [("hotkey", ("ctrl", "s")), ("type", "hi\n")]


def test_an_unchanged_screen_after_a_fast_action_skips_the_fast_model(tmp_path, monkeypatch):
    monkeypatch.setattr(loop_mod, "_changed", lambda a, b: False)
    res, fake = fast_run(tmp_path, monkeypatch, [dec("scroll_down"), dec("done")],
                         [{"action": "key", "text": "esc"}, {"action": "done"}])
    assert [h["by"] for h in res.history] == ["fast", "vision"]


def test_remember_notes_are_kept_and_shown_every_turn(tmp_path, monkeypatch):
    seen = []
    replies = iter([{"action": "key", "text": "esc", "remember": "GPT-4: 41.2"}, {"action": "key", "text": "tab"},
                    {"action": "done"}])

    def decide(screen, items, other, history, notes="", output=None):
        seen.append(notes)
        return dict(next(replies))
    fake = FakeDesktop()
    screen = SimpleNamespace(image=Image.new("RGB", (160, 90)), app="gedit", to_points=lambda it: (0.0, 0.0))
    monkeypatch.setattr(loop_mod, "desktop", fake)
    lp = Loop(LoopConfig(goal="g", out=tmp_path, writer=None, act=True, max_steps=10))
    monkeypatch.setattr(lp, "look", lambda: (screen, [], []))
    monkeypatch.setattr(lp, "decide", decide)
    assert lp.run().result == "done"
    assert seen == ["", "GPT-4: 41.2", "GPT-4: 41.2"]


def test_shell_output_comes_back_once_and_never_touches_the_screen(tmp_path, monkeypatch):
    outputs = []
    replies = iter([{"action": "shell", "text": "cat a.csv"}, {"action": "key", "text": "esc"}, {"action": "done"}])

    def decide(screen, items, other, history, notes="", output=None):
        outputs.append(output)
        return dict(next(replies))
    fake = FakeDesktop()
    screen = SimpleNamespace(image=Image.new("RGB", (160, 90)), app="gedit", to_points=lambda it: (0.0, 0.0))
    monkeypatch.setattr(loop_mod, "desktop", fake)
    lp = Loop(LoopConfig(goal="g", out=tmp_path, writer=None, act=True, max_steps=10, shell=lambda c: f"out of {c}"))
    monkeypatch.setattr(lp, "look", lambda: (screen, [], []))
    monkeypatch.setattr(lp, "decide", decide)
    res = lp.run()
    assert outputs == [None, "out of cat a.csv", None]
    assert fake.done == [("press", "esc", False)]
    assert res.history[0]["result"] == "ran; output in last_shell_output"


def test_without_a_shell_the_action_is_refused_and_left_out_of_the_prompt(tmp_path, monkeypatch):
    res, fake = run(tmp_path, monkeypatch, [{"action": "shell", "text": "ls"}, {"action": "done"}])
    assert res.history[0]["result"] == "no shell here"
    assert "- shell:" not in loop_mod.SYSTEM.replace(loop_mod.SHELL_LINE, "")


def test_repeated_actions_get_a_warning(tmp_path, monkeypatch):
    packets = []
    lp = Loop(LoopConfig(goal="g", out=tmp_path, writer=None))
    monkeypatch.setattr(loop_mod, "_structured", lambda w, s, packet, *a, **k: packets.append(packet) or {"action": "done"})
    screen = SimpleNamespace(image=None, app="x")
    same = {"action": "type", "item": None, "text": "cat a.csv\n"}
    lp.decide(screen, [], [], [same, same])
    lp.decide(screen, [], [], [same, same, same])
    assert "warning" not in packets[0] and "cat a.csv" in packets[1]["warning"]


def test_an_action_the_desktop_refuses_is_reported_and_the_run_goes_on(tmp_path, monkeypatch):
    from typesafe_computer_use.models import Missed

    def refuse(p):
        raise Missed("Windows would not move the cursor")
    res, fake = run(tmp_path, monkeypatch, [{"action": "click", "item": 3}, {"action": "key", "text": "nosuchkey"},
                                            {"action": "done"}])
    assert res.result == "done"
    monkeypatch.setattr(FakeDesktop, "click_at", lambda self, p: refuse(p))
    monkeypatch.setattr(FakeDesktop, "press", lambda self, k, command=False: (_ for _ in ()).throw(ValueError("no key")))
    res, fake = run(tmp_path, monkeypatch, [{"action": "click", "item": 3}, {"action": "key", "text": "nosuchkey"},
                                            {"action": "done"}])
    assert res.result == "done" and [h["result"][:7] for h in res.history] == ["failed:", "failed:"]
