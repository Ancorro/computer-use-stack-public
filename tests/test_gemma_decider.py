from types import SimpleNamespace

from cu_stack.gemma_decider import GemmaDecider


def q(n):
    return SimpleNamespace(instructions="Which?", criteria={str(i): f"option {i}" for i in range(n)})


def tok(text, logprob=-0.1, top=()):
    return {"token": text, "logprob": logprob, "top_logprobs": [{"token": t, "logprob": lp} for t, lp in top]}


def decider(reply):
    d = GemmaDecider("http://x:11434/v1", "gemma")
    d.prompts = []
    d._generate = lambda prompt, tokens: d.prompts.append(prompt) or reply
    return d


def test_one_request_answers_every_question():
    reply = [tok("kind"), tok(":"), tok(" B", top=[(" B", -0.1), (" A", -2.4), ("Z", -1.0)]), tok("\n"), tok("item"), tok(":"),
             tok(" 4", -0.1), tok("1", -0.2), tok("\n"), tok("site"), tok(":"), tok(" A", top=[(" A", 0.0)])]
    d = decider(reply)
    answers = d.system_one(state={"goal": "g"}, questions={"kind": q(3), "item": q(60), "site": q(2), "app": q(1)}).answers
    assert len(d.prompts) == 1
    assert answers["kind"].choice == "1" and 0.85 < answers["kind"].confidence < 0.95
    assert answers["item"].choice == "40" and 0.7 < answers["item"].confidence < 0.8
    assert answers["site"].choice == "0" and answers["app"].confidence == 1.0 and d.misses == 0


def test_a_missing_or_bad_answer_is_a_miss():
    d = decider([tok("kind"), tok(":"), tok(" C", top=[(" C", 0.0)]), tok("\n"), tok("item"), tok(":"), tok(" 99", 0.0)])
    answers = d.system_one(state={}, questions={"kind": q(3), "item": q(30), "site": q(2)}).answers
    assert answers["kind"].choice == "2"
    assert answers["item"].confidence == 0.0 and answers["site"].confidence == 0.0 and d.misses == 2
