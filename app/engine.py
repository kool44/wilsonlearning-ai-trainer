"""Session engine: owns the step sequence. The LLM only fills each step."""
from __future__ import annotations

import uuid

from . import content, db
from .llm import get_provider

_provider = None


def provider():
    global _provider
    if _provider is None:
        _provider = get_provider()
    return _provider


def _new_state(module_id: str, learner_name: str | None) -> dict:
    return {
        "module_id": module_id,
        "learner_name": learner_name,
        "step_idx": 0,
        "phase": "teaching",       # teaching | asked | roleplay | done
        "beats": [],
        "beat_idx": 0,
        "attempt": 0,
        "transcript": [],          # roleplay turns for current step
        "scores": {},              # step_id -> {score, max_score}
        "history": [],             # all chat messages
    }


def _step(module: dict, state: dict) -> dict | None:
    idx = state["step_idx"]
    return module["steps"][idx] if idx < len(module["steps"]) else None


def _progress(module: dict, state: dict) -> dict:
    step = _step(module, state)
    return {
        "step_index": state["step_idx"],
        "step_total": len(module["steps"]),
        "step_id": step["id"] if step else None,
        "step_title": step["title"] if step else "Complete",
        "step_type": step["type"] if step else None,
        "phase": state["phase"],
        "attempt": state["attempt"],
        "scores": state["scores"],
        "persona": step.get("persona") if step and step["type"] == "roleplay" else None,
        "beat": state.get("beat_idx", 0) + 1,
        "beats": len(state.get("beats", [])),
        "turns_used": sum(1 for t in state["transcript"] if t["role"] == "salesperson"),
        "max_turns": step.get("max_turns") if step else None,
        "steps": [{"id": s["id"], "title": s["title"], "type": s["type"],
                   "max_score": len(s["rubric"]),
                   "pass_score": s.get("pass_score", 1)} for s in module["steps"]],
    }


def _bot(state: dict, text: str, kind: str, step: dict | None, extra: dict | None = None) -> dict:
    msg = {"role": "bot", "kind": kind, "text": text, "step_id": step["id"] if step else None}
    if extra:
        msg.update(extra)
    state["history"].append(msg)
    return msg


def _enter_step(module: dict, state: dict) -> list[dict]:
    """Produce the bot message(s) that open the current step."""
    step = _step(module, state)
    state["attempt"] = 0
    state["transcript"] = []
    if step is None:
        state["phase"] = "done"
        total = sum(v["score"] for v in state["scores"].values())
        mx = sum(v["max_score"] for v in state["scores"].values())
        return [_bot(state, f"That completes the Relating module. You scored {total} out of {mx} across the exercises. "
                            "Remember the formula: Credibility plus Empathy equals Trust. Use PPP and a Ben Duffy on every call.",
                     "complete", None)]
    if step["type"] == "roleplay":
        state["phase"] = "roleplay"
        intro = " ".join(step["teach_points"])
        p = step["persona"]
        brief = f"{intro} You are meeting {p['name']}, {p['role']}. {p['situation'].split('.')[0]}. Begin when you're ready."
        msgs = [_bot(state, brief, "teach", step)]
        return msgs
    state["beats"] = provider().teach_beats(module, step, state.get("learner_name"), None)
    state["beat_idx"] = 0
    return _emit_beat(state, step)


ACKS = ("ok", "okay", "yes", "yep", "yeah", "sure", "go on", "next", "continue", "got it", "makes sense", "ready",
        "mm", "mhm", "uh huh", "right", "fine", "understood", "clear", "carry on", "keep going", "yes please", "k")


def _is_ack(text: str) -> bool:
    t = text.lower().strip(" .!,")
    return t == "" or t in ACKS or (len(t.split()) <= 3 and any(t.startswith(a) for a in ACKS))


def _emit_beat(state: dict, step: dict) -> list[dict]:
    """Send the current beat. The last beat is the step question, so entering it switches to 'asked'."""
    beats = state["beats"]
    i = state["beat_idx"]
    if i >= len(beats):
        i = len(beats) - 1
    last = i == len(beats) - 1
    state["phase"] = "asked" if last else "teaching"
    return [_bot(state, beats[i], "teach", step, {"beat": i + 1, "beats": len(beats), "last_beat": last})]


def start(module_id: str, learner_name: str | None = None) -> dict:
    module = content.get(module_id)
    session_id = uuid.uuid4().hex[:12]
    state = _new_state(module_id, learner_name)
    msgs = _enter_step(module, state)
    db.save(session_id, module_id, state)
    return {"session_id": session_id, "messages": msgs, "progress": _progress(module, state)}


def get(session_id: str) -> dict | None:
    state = db.load(session_id)
    if not state:
        return None
    module = content.get(state["module_id"])
    return {"session_id": session_id, "messages": state["history"], "progress": _progress(module, state)}


def message(session_id: str, text: str) -> dict | None:
    state = db.load(session_id)
    if not state:
        return None
    module = content.get(state["module_id"])
    step = _step(module, state)
    text = (text or "").strip()
    state["history"].append({"role": "user", "text": text, "step_id": step["id"] if step else None})
    out: list[dict] = []

    if state["phase"] == "done" or step is None:
        out.append(_bot(state, "The module is complete. Start a new session to run it again.", "info", None))
    elif state["phase"] == "roleplay":
        out += _roleplay_turn(module, state, step, text)
    elif state["phase"] == "teaching":
        if _is_ack(text):
            state["beat_idx"] += 1
            out += _emit_beat(state, step)
        else:
            covered = state["beats"][: state["beat_idx"] + 1]
            out.append(_bot(state, provider().answer_question(module, step, text, covered), "answer", step))
            state["beat_idx"] += 1
            out += _emit_beat(state, step)
    elif text.endswith("?") and len(text.split()) <= 25:
        # A question instead of an answer: answer it, then re-ask the step question.
        out.append(_bot(state, provider().answer_question(module, step, text, state.get("beats", [])), "answer", step))
        out += _emit_beat(state, step)
    else:
        out += _answer_turn(module, state, step, text)

    db.save(session_id, state["module_id"], state)
    return {"session_id": session_id, "messages": out, "progress": _progress(module, state)}


def _answer_turn(module: dict, state: dict, step: dict, text: str) -> list[dict]:
    state["attempt"] += 1
    max_attempts = step.get("max_attempts", 2)
    last = state["attempt"] >= max_attempts
    g = provider().grade(module, step, text, state["attempt"], last)
    passed = g["score"] >= step.get("pass_score", 1)
    out = [_bot(state, g["feedback"], "feedback", step,
                {"score": g["score"], "max_score": g["max_score"], "met": g["met"], "missed": g["missed"],
                 "passed": passed})]
    if passed or last:
        prev = state["scores"].get(step["id"], {"score": 0})
        state["scores"][step["id"]] = {"score": max(g["score"], prev["score"]), "max_score": g["max_score"]}
        state["step_idx"] += 1
        out += _enter_step(module, state)
    else:
        state["scores"][step["id"]] = {"score": g["score"], "max_score": g["max_score"]}
        out.append(_bot(state, "Have another go at it.", "retry", step))
    return out


def _roleplay_turn(module: dict, state: dict, step: dict, text: str) -> list[dict]:
    end_words = ("end call", "end the call", "stop the call", "finish call")
    wants_end = any(w in text.lower() for w in end_words)
    if not wants_end:
        state["transcript"].append({"role": "salesperson", "text": text})
    sales_turns = sum(1 for t in state["transcript"] if t["role"] == "salesperson")
    out: list[dict] = []
    if wants_end or sales_turns >= step.get("max_turns", 6):
        g = provider().grade_roleplay(module, step, state["transcript"])
        passed = g["score"] >= step.get("pass_score", 1)
        state["scores"][step["id"]] = {"score": g["score"], "max_score": g["max_score"]}
        out.append(_bot(state, g["feedback"], "feedback", step,
                        {"score": g["score"], "max_score": g["max_score"], "met": g["met"], "missed": g["missed"],
                         "passed": passed}))
        state["step_idx"] += 1
        out += _enter_step(module, state)
        return out
    reply = provider().roleplay_reply(module, step, state["transcript"])
    state["transcript"].append({"role": "customer", "text": reply})
    out.append(_bot(state, reply, "customer", step, {"speaker": step["persona"]["name"]}))
    return out


def command(session_id: str, cmd: str) -> dict | None:
    state = db.load(session_id)
    if not state:
        return None
    module = content.get(state["module_id"])
    step = _step(module, state)
    out: list[dict] = []
    if cmd == "skip" and step is not None:
        state["scores"].setdefault(step["id"], {"score": 0, "max_score": len(step["rubric"])})
        state["step_idx"] += 1
        out += _enter_step(module, state)
    elif cmd == "continue" and step is not None and state["phase"] == "teaching":
        state["beat_idx"] += 1
        out += _emit_beat(state, step)
    elif cmd == "repeat" and step is not None:
        if step["type"] == "roleplay":
            out.append(_bot(state, " ".join(step["teach_points"]), "teach", step))
        elif state["phase"] in ("teaching", "asked") and state.get("beats"):
            out += _emit_beat(state, step)
        else:
            state["beats"] = provider().teach_beats(module, step, state.get("learner_name"),
                                                    "The learner asked you to explain this step again, differently.")
            state["beat_idx"] = 0
            out += _emit_beat(state, step)
    elif cmd == "hint" and step is not None and state["phase"] == "roleplay":
        out.append(_bot(state, provider().hint(module, step, state["transcript"]), "hint", step))
    elif cmd == "end_call" and step is not None and state["phase"] == "roleplay":
        out += _roleplay_turn(module, state, step, "end call")
    elif cmd == "restart":
        state.update(_new_state(state["module_id"], state.get("learner_name")))
        out += _enter_step(module, state)
    else:
        out.append(_bot(state, "Unknown command.", "info", step))
    db.save(session_id, state["module_id"], state)
    return {"session_id": session_id, "messages": out, "progress": _progress(module, state)}
