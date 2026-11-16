"""Session engine: owns the step sequence. The LLM only fills in open answers, Q&A and the role-play.

Each step = a short authored script (instant, no LLM call) + one activity drawn at random from the step's pool:
  choice  multiple choice, graded locally and instantly
  order   put items in sequence, graded locally and instantly
  open    free answer, graded by the LLM against a rubric
Role-play steps pick one of several customer personas at random.
"""
from __future__ import annotations

import random
import re
import uuid

from . import content, db
from .llm import get_provider

STATE_VERSION = 2
LETTERS = "ABCDEFGH"
_provider = None


def provider():
    global _provider
    if _provider is None:
        _provider = get_provider()
    return _provider


def _new_state(module_id: str, learner_name: str | None) -> dict:
    return {
        "v": STATE_VERSION,
        "module_id": module_id,
        "learner_name": learner_name,
        "step_idx": 0,
        "phase": "asked",          # asked | roleplay | done
        "act": None,               # the activity drawn for the current step
        "persona": None,           # the persona drawn for a role-play step
        "attempt": 0,
        "transcript": [],
        "scores": {},              # step_id -> {score, max_score, passed}
        "streak": 0,
        "history": [],
    }


def _load(session_id: str) -> dict | None:
    state = db.load(session_id)
    if not state or state.get("v") != STATE_VERSION:
        return None
    return state


def _step(module: dict, state: dict) -> dict | None:
    idx = state["step_idx"]
    return module["steps"][idx] if idx < len(module["steps"]) else None


def _progress(module: dict, state: dict) -> dict:
    step = _step(module, state)
    act = state.get("act") or {}
    return {
        "module_id": state["module_id"],
        "step_index": state["step_idx"],
        "step_total": len(module["steps"]),
        "step_id": step["id"] if step else None,
        "step_title": step["title"] if step else "Complete",
        "step_type": step["type"] if step else None,
        "phase": state["phase"],
        "activity_type": act.get("type"),
        "attempt": state["attempt"],
        "scores": state["scores"],
        "streak": state.get("streak", 0),
        "persona": state.get("persona") if state["phase"] == "roleplay" else None,
        "turns_used": sum(1 for t in state["transcript"] if t["role"] == "salesperson"),
        "max_turns": step.get("max_turns") if step else None,
        "steps": [{"id": s["id"], "title": s["title"], "type": s["type"]} for s in module["steps"]],
    }


def _bot(state: dict, text: str, kind: str, step: dict | None, extra: dict | None = None) -> dict:
    msg = {"role": "bot", "kind": kind, "text": text, "step_id": step["id"] if step else None}
    if extra:
        msg.update(extra)
    state["history"].append(msg)
    return msg


def _personal(text: str, name: str | None) -> str:
    if name:
        return text.replace("{name}", name)
    text = re.sub(r"\s\{name\},", ",", text)
    text = re.sub(r",\s*\{name\}", "", text)
    text = re.sub(r"\{name\},\s*", "", text)
    text = text.replace("{name}", "").replace("  ", " ")
    return text[:1].upper() + text[1:]


# ------------------------------------------------------------------ activities
def _draw_activity(step: dict) -> dict:
    act = dict(random.choice(step["activities"]))
    if act["type"] == "choice":
        opts = list(enumerate(act["options"]))
        random.shuffle(opts)
        act["shown"] = [{"key": LETTERS[i], "text": t} for i, (_, t) in enumerate(opts)]
        act["correct_key"] = LETTERS[[orig for orig, _ in opts].index(act.get("answer", 0))]
        act["max_score"] = 1
    elif act["type"] == "order":
        items = list(act["items"])
        shuffled = items[:]
        while len(items) > 1 and shuffled == items:
            random.shuffle(shuffled)
        act["shown"] = [{"key": LETTERS[i], "text": t} for i, t in enumerate(shuffled)]
        act["correct_order"] = [LETTERS[shuffled.index(t)] for t in items]
        act["max_score"] = len(items)
    else:
        act["max_score"] = len(act["rubric"])
    return act


def _activity_msg(state: dict, step: dict) -> dict:
    act = state["act"]
    public = {"type": act["type"], "prompt": act["prompt"]}
    if act["type"] in ("choice", "order"):
        public["options"] = act["shown"]
    label = {"choice": "Quick check", "order": "Put it in order", "open": "Your turn"}[act["type"]]
    return _bot(state, act["prompt"], "activity", step, {"activity": public, "label": label})


def _graded_step(step: dict, act: dict) -> dict:
    """The step as the LLM grader sees it: question/rubric/model answer come from the drawn activity."""
    return {**step, "question": act["prompt"], "rubric": act["rubric"], "model_answer": act.get("model_answer")}


_SPOKEN = {"a": "A", "ay": "A", "eh": "A", "one": "A", "first": "A", "1": "A",
           "b": "B", "be": "B", "bee": "B", "two": "B", "second": "B", "2": "B",
           "c": "C", "see": "C", "sea": "C", "three": "C", "third": "C", "3": "C",
           "d": "D", "dee": "D", "four": "D", "fourth": "D", "4": "D",
           "e": "E", "five": "E", "fifth": "E", "5": "E"}


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9']+", text.lower())


def _parse_choice(text: str, shown: list[dict]) -> str | None:
    keys = {o["key"] for o in shown}
    w = _words(text)
    for skip in ("option", "answer", "letter", "is", "its", "it's", "the", "i", "think", "say", "pick", "choose", "go", "with"):
        while w and w[0] == skip:
            w = w[1:]
    if w and _SPOKEN.get(w[0]) in keys and (len(w) <= 3 or w[0] in ("a", "b", "c", "d")):
        if not (w[0] == "a" and len(w) > 3):     # "a rep who..." is prose, not option A
            return _SPOKEN[w[0]]
    # Fuzzy match against option text (voice answers often paraphrase the option).
    said = set(_words(text))
    best, best_score = None, 0.0
    for o in shown:
        ow = set(_words(o["text"])) - {"the", "a", "and", "to", "of", "you", "is", "it", "so"}
        if not ow:
            continue
        s = len(ow & said) / len(ow)
        if s > best_score:
            best, best_score = o["key"], s
    return best if best_score >= 0.5 else None


def _parse_order(text: str, n: int) -> list[str] | None:
    keys = [_SPOKEN.get(w) for w in _words(text.replace("order:", " "))]
    keys = [k for k in keys if k and k in LETTERS[:n]]
    return keys if len(keys) == n and len(set(keys)) == n else None


PRAISE = ["Spot on!", "Nailed it.", "Exactly right.", "Yes, that's it.", "Perfect."]
NUDGE = ["Not quite.", "Close, but no.", "Good try, but not this time."]


def _praise(state: dict) -> str:
    s = state["streak"]
    base = random.choice(PRAISE)
    if s >= 3:
        return f"{base} That's {s} in a row!"
    return base


def _record(state: dict, step: dict, score: int, max_score: int, passed: bool) -> None:
    prev = state["scores"].get(step["id"])
    if prev and prev["score"] > score:
        return
    state["scores"][step["id"]] = {"score": score, "max_score": max_score, "passed": passed}


# ------------------------------------------------------------------ steps
def _enter_step(module: dict, state: dict) -> list[dict]:
    step = _step(module, state)
    state["attempt"] = 0
    state["transcript"] = []
    state["act"] = None
    state["persona"] = None
    name = state.get("learner_name")
    if step is None:
        state["phase"] = "done"
        total = sum(v["score"] for v in state["scores"].values())
        mx = sum(v["max_score"] for v in state["scores"].values())
        who = f"Great work, {name}." if name else "Great work."
        return [_bot(state, f"{who} That's the Relating module done. You scored {total} out of {mx}. "
                            "Remember: Credibility plus Empathy equals Trust. Open with a PPP and share your Ben Duffy on every call.",
                     "complete", None)]
    out = [_bot(state, _personal(b, name), "teach", step, {"beat": i + 1, "beats": len(step["script"])})
           for i, b in enumerate(step.get("script", []))]
    if step["type"] == "roleplay":
        state["phase"] = "roleplay"
        p = random.choice(step.get("personas") or [step["persona"]])
        state["persona"] = p
        first = p["situation"].split(". ")[0].rstrip(".")
        out.append(_bot(state, f"You're meeting {p['name']}, {p['role']}. {first}. Go ahead and open the meeting.",
                        "teach", step, {"persona_intro": True}))
        return out
    state["phase"] = "asked"
    state["act"] = _draw_activity(step)
    out.append(_activity_msg(state, step))
    return out


def _advance(module: dict, state: dict) -> list[dict]:
    state["step_idx"] += 1
    return _enter_step(module, state)


def start(module_id: str, learner_name: str | None = None) -> dict:
    module = content.get(module_id)
    session_id = uuid.uuid4().hex[:12]
    name = (learner_name or "").strip()[:40] or None
    if name:
        name = name[0].upper() + name[1:]
    state = _new_state(module_id, name)
    msgs = _enter_step(module, state)
    db.save(session_id, module_id, state)
    return {"session_id": session_id, "messages": msgs, "progress": _progress(module, state)}


def get(session_id: str) -> dict | None:
    state = _load(session_id)
    if not state:
        return None
    module = content.get(state["module_id"])
    return {"session_id": session_id, "messages": state["history"], "progress": _progress(module, state)}


def _looks_like_question(text: str) -> bool:
    t = text.lower().strip()
    return t.endswith("?") or (len(t.split()) <= 25 and t.split()[0:1] in (["what"], ["why"], ["how"], ["can"], ["could"], ["is"], ["does"], ["do"]))


def message(session_id: str, text: str) -> dict | None:
    state = _load(session_id)
    if not state:
        return None
    module = content.get(state["module_id"])
    step = _step(module, state)
    text = (text or "").strip()
    state["history"].append({"role": "user", "text": text, "step_id": step["id"] if step else None})
    out: list[dict] = []

    if state["phase"] == "done" or step is None:
        out.append(_bot(state, "The module is complete. Tap Restart to run it again, with fresh questions.", "info", None))
    elif state["phase"] == "roleplay":
        out += _roleplay_turn(module, state, step, text)
    else:
        act = state["act"]
        if act["type"] == "choice":
            out += _choice_turn(module, state, step, act, text)
        elif act["type"] == "order":
            out += _order_turn(module, state, step, act, text)
        elif _looks_like_question(text) and len(text.split()) <= 25:
            out.append(_bot(state, provider().answer_question(module, step, text, step.get("script", [])), "answer", step))
            out.append(_activity_msg(state, step))
        else:
            out += _open_turn(module, state, step, act, text)

    db.save(session_id, state["module_id"], state)
    return {"session_id": session_id, "messages": out, "progress": _progress(module, state)}


def _not_understood(module, state, step, act, text, how: str) -> list[dict]:
    if _looks_like_question(text):
        return [_bot(state, provider().answer_question(module, step, text, step.get("script", [])), "answer", step),
                _activity_msg(state, step)]
    return [_bot(state, how, "info", step)]


def _choice_turn(module, state, step, act, text) -> list[dict]:
    key = _parse_choice(text, act["shown"])
    if key is None:
        return _not_understood(module, state, step, act, text, "Tap one of the options, or say the letter, like 'B'.")
    correct = key == act["correct_key"]
    right = next(o for o in act["shown"] if o["key"] == act["correct_key"])
    if correct:
        state["streak"] += 1
        fb = f"{_praise(state)} {act['why']}"
    else:
        state["streak"] = 0
        fb = f"{random.choice(NUDGE)} It's {right['key']}: {right['text']}. {act['why']}"
    _record(state, step, int(correct), 1, correct)
    out = [_bot(state, fb, "feedback", step, {"score": int(correct), "max_score": 1, "passed": correct,
                                               "chosen": key, "correct": act["correct_key"], "quick": True})]
    return out + _advance(module, state)


def _order_turn(module, state, step, act, text) -> list[dict]:
    n = len(act["correct_order"])
    got = _parse_order(text, n)
    if got is None:
        return _not_understood(module, state, step, act, text,
                               f"Tap the items in order, or say all {n} letters, like 'C, A, B'.")
    right = sum(1 for a, b in zip(got, act["correct_order"]) if a == b)
    perfect = right == n
    if perfect:
        state["streak"] += 1
        fb = f"{_praise(state)} {act['why']}"
    else:
        state["streak"] = 0
        fb = f"{right} of {n} in the right spot. The order is: {', '.join(act['items'])}. {act['why']}"
    _record(state, step, right, n, perfect)
    out = [_bot(state, fb, "feedback", step, {"score": right, "max_score": n, "passed": perfect,
                                               "chosen_order": got, "correct_order": act["correct_order"], "quick": True})]
    return out + _advance(module, state)


def _open_turn(module, state, step, act, text) -> list[dict]:
    state["attempt"] += 1
    last = state["attempt"] >= act.get("max_attempts", 2)
    g = provider().grade(module, _graded_step(step, act), text, state["attempt"], last)
    passed = g["score"] >= act.get("pass_score", 1)
    state["streak"] = state["streak"] + 1 if passed else 0
    _record(state, step, g["score"], g["max_score"], passed)
    out = [_bot(state, g["feedback"], "feedback", step,
                {"score": g["score"], "max_score": g["max_score"], "met": g["met"], "missed": g["missed"], "passed": passed})]
    if passed or last:
        return out + _advance(module, state)
    out.append(_bot(state, "Have another go. Just add what's missing.", "retry", step))
    return out


def _roleplay_turn(module: dict, state: dict, step: dict, text: str) -> list[dict]:
    rp_step = {**step, "persona": state["persona"]}
    end_words = ("end call", "end the call", "stop the call", "finish call")
    wants_end = any(w in text.lower() for w in end_words)
    if not wants_end:
        state["transcript"].append({"role": "salesperson", "text": text})
    sales_turns = sum(1 for t in state["transcript"] if t["role"] == "salesperson")
    if wants_end or sales_turns >= step.get("max_turns", 6):
        if not sales_turns:
            g = {"score": 0, "max_score": len(step["rubric"]), "met": [], "missed": step["rubric"],
                 "feedback": "You ended the call before saying anything, so there's nothing to score yet. Let's move on."}
        else:
            g = provider().grade_roleplay(module, rp_step, state["transcript"])
        passed = g["score"] >= step.get("pass_score", 1)
        _record(state, step, g["score"], g["max_score"], passed)
        out = [_bot(state, g["feedback"], "feedback", step,
                    {"score": g["score"], "max_score": g["max_score"], "met": g["met"], "missed": g["missed"],
                     "passed": passed})]
        return out + _advance(module, state)
    reply = provider().roleplay_reply(module, rp_step, state["transcript"])
    state["transcript"].append({"role": "customer", "text": reply})
    return [_bot(state, reply, "customer", step, {"speaker": state["persona"]["name"]})]


def command(session_id: str, cmd: str) -> dict | None:
    state = _load(session_id)
    if not state:
        return None
    module = content.get(state["module_id"])
    step = _step(module, state)
    out: list[dict] = []
    if cmd == "skip" and step is not None:
        mx = (state.get("act") or {}).get("max_score") or len(step.get("rubric", [])) or 1
        state["scores"].setdefault(step["id"], {"score": 0, "max_score": mx, "passed": False})
        state["streak"] = 0
        out += _advance(module, state)
    elif cmd == "repeat" and step is not None:
        name = state.get("learner_name")
        out += [_bot(state, _personal(b, name), "teach", step, {"beat": i + 1, "beats": len(step["script"])})
                for i, b in enumerate(step.get("script", []))]
        if state["phase"] == "asked" and state.get("act"):
            out.append(_activity_msg(state, step))
    elif cmd == "hint" and step is not None and state["phase"] == "roleplay":
        out.append(_bot(state, provider().hint(module, {**step, "persona": state["persona"]}, state["transcript"]), "hint", step))
    elif cmd == "end_call" and step is not None and state["phase"] == "roleplay":
        out += _roleplay_turn(module, state, step, "end call")
    elif cmd == "restart":
        state.update(_new_state(state["module_id"], state.get("learner_name")))
        out += _enter_step(module, state)
    else:
        out.append(_bot(state, "That isn't available right now.", "info", step))
    db.save(session_id, state["module_id"], state)
    return {"session_id": session_id, "messages": out, "progress": _progress(module, state)}
