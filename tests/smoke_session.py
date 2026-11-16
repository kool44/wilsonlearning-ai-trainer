"""End-to-end smoke test of the session engine with the mock provider (no API key needed).

Run:  LLM_PROVIDER=mock python -m tests.smoke_session
"""
import os
import random
import sys
import tempfile
import time

os.environ.setdefault("LLM_PROVIDER", "mock")
os.environ.setdefault("DB_PATH", os.path.join(tempfile.mkdtemp(), "t.db"))

from fastapi.testclient import TestClient  # noqa: E402

from app import engine  # noqa: E402
from app.main import app  # noqa: E402

GOOD = ("When a new vendor called me last year the rep opened by explaining exactly why he was calling, how long it "
        "would take, and what I would get out of it, then asked if that worked for me. He had clearly thought about "
        "what I would be worried about, named it before I did, and listened. That raised my comfort fast. "
        "Relationship tension dropped and I was willing to talk about the actual task.")
WEAK = "Not sure, trust is important I guess."


def current_act(sid):
    return engine.db.load(sid)["act"]


def answer(c, sid, r, right=True):
    """Answer whatever activity is showing. Returns the response."""
    act = current_act(sid)
    if act["type"] == "choice":
        key = act["correct_key"] if right else next(o["key"] for o in act["shown"] if o["key"] != act["correct_key"])
        return c.post(f"/api/session/{sid}/message", json={"text": key}).json()
    if act["type"] == "order":
        order = act["correct_order"] if right else list(reversed(act["correct_order"]))
        return c.post(f"/api/session/{sid}/message", json={"text": "order: " + ", ".join(order)}).json()
    return c.post(f"/api/session/{sid}/message", json={"text": GOOD if right else WEAK}).json()


def main() -> int:
    random.seed(7)
    with TestClient(app) as c:
        assert c.get("/api/health").json()["ok"]
        mods = c.get("/api/modules").json()
        t0 = time.time()
        r = c.post("/api/session", json={"module_id": mods[0]["id"], "learner_name": "Sam"}).json()
        assert time.time() - t0 < 1.0, "session start must not wait on the LLM"
        sid = r["session_id"]
        kinds = [m["kind"] for m in r["messages"]]
        assert kinds[:-1] == ["teach"] * (len(kinds) - 1) and kinds[-1] == "activity", kinds
        assert "Sam" in r["messages"][0]["text"] and "{name}" not in r["messages"][0]["text"]
        assert r["progress"]["phase"] == "asked"
        print(f"start ok: {len(kinds) - 1} beats + {r['messages'][-1]['activity']['type']} activity")

        # no-name personalisation
        r2 = c.post("/api/session", json={"module_id": mods[0]["id"]}).json()
        assert "{name}" not in r2["messages"][0]["text"] and r2["messages"][0]["text"].startswith("Hey, welcome"), r2["messages"][0]["text"]

        # force a choice activity on step 1 to test parsing
        st = engine.db.load(sid)
        st["act"] = engine._draw_activity({"activities": [a for a in engine.content.get(mods[0]["id"])["steps"][0]["activities"] if a["type"] == "choice"]})
        engine.db.save(sid, mods[0]["id"], st)
        r = c.post(f"/api/session/{sid}/message", json={"text": "hmm"}).json()
        assert r["messages"][0]["kind"] == "info" and r["progress"]["step_index"] == 0
        r = c.post(f"/api/session/{sid}/message", json={"text": "What is No Trust?"}).json()
        assert [m["kind"] for m in r["messages"]] == ["answer", "activity"], r["messages"]
        act = current_act(sid)
        right_text = next(o["text"] for o in act["shown"] if o["key"] == act["correct_key"])
        r = c.post(f"/api/session/{sid}/message", json={"text": right_text}).json()   # fuzzy text match
        fb = r["messages"][0]
        assert fb["kind"] == "feedback" and fb["passed"] and fb["quick"], fb
        assert r["progress"]["step_index"] == 1 and r["progress"]["streak"] == 1
        print("choice parse/answer ok")

        # things people say instead of answering never get graded as answers
        step_before = r["progress"]["step_index"]
        for said, kind in (("say that again", "activity"), ("ok", "info"), ("", "info")):
            r = c.post(f"/api/session/{sid}/message", json={"text": said}).json()
            assert r["messages"][-1]["kind"] == kind and r["progress"]["step_index"] == step_before, (said, r["messages"])
            assert r["progress"]["attempt"] == 0
        print("spoken commands ok")

        # wrong answer resets streak
        r = answer(c, sid, r, right=False)
        assert r["progress"]["streak"] == 0 and r["progress"]["step_index"] == 2
        print("wrong answer ok")

        # open-question retry path: find an open activity
        st = engine.db.load(sid)
        step = engine.content.get(mods[0]["id"])["steps"][st["step_idx"]]
        opens = [a for a in step["activities"] if a["type"] == "open"]
        if opens:
            st["act"] = engine._draw_activity({"activities": opens}); engine.db.save(sid, mods[0]["id"], st)
            r = c.post(f"/api/session/{sid}/message", json={"text": WEAK}).json()
            assert [m["kind"] for m in r["messages"]] == ["feedback", "retry"], r["messages"]
            r = c.post(f"/api/session/{sid}/message", json={"text": WEAK}).json()
            assert r["progress"]["step_index"] == 3
            print("open retry/advance ok")

        while r["progress"]["phase"] == "asked":
            r = answer(c, sid, r)
        assert r["progress"]["phase"] == "roleplay", r["progress"]
        persona = r["progress"]["persona"]["name"]
        print(f"reached roleplay at step {r['progress']['step_index'] + 1} with {persona}")

        r = c.post(f"/api/session/{sid}/message", json={"text": "Thanks for the time. The purpose of this meeting is to understand your priorities. Process: a few questions you may be wondering about us, then your situation, about 25 minutes. Payoff: you learn if we are worth more time. Does that sound ok?"}).json()
        assert r["messages"][0]["kind"] == "customer" and r["messages"][0]["speaker"] == persona
        r = c.post(f"/api/session/{sid}/command", json={"cmd": "hint"}).json()
        assert r["messages"][0]["kind"] == "hint"
        r = c.post(f"/api/session/{sid}/command", json={"cmd": "end_call"}).json()
        assert r["messages"][0]["kind"] == "feedback" and "score" in r["messages"][0]
        print("roleplay graded:", r["messages"][0]["score"], "/", r["messages"][0]["max_score"])

        while r["progress"]["phase"] == "asked":
            r = answer(c, sid, r)
        assert r["progress"]["phase"] == "done" and r["messages"][-1]["kind"] == "complete"
        print("module complete:", r["messages"][-1]["text"][:90])

        g = c.get(f"/api/session/{sid}").json()
        assert g["progress"]["phase"] == "done"
        r = c.post(f"/api/session/{sid}/command", json={"cmd": "restart"}).json()
        assert r["progress"]["step_index"] == 0 and r["progress"]["scores"] == {}
        r = c.post(f"/api/session/{sid}/command", json={"cmd": "repeat"}).json()
        assert r["messages"][-1]["kind"] == "activity"
        r = c.post(f"/api/session/{sid}/command", json={"cmd": "skip"}).json()
        assert r["progress"]["step_index"] == 1
        assert c.get("/api/session/doesnotexist").status_code == 404
        print("commands ok")

        # every activity in the pack can be drawn and answered correctly
        module = engine.content.get(mods[0]["id"])
        for s in module["steps"]:
            for a in s.get("activities", []):
                d = engine._draw_activity({"activities": [a]})
                if d["type"] == "choice":
                    assert d["shown"][[o["key"] for o in d["shown"]].index(d["correct_key"])]["text"] == a["options"][a.get("answer", 0)]
                    assert engine._parse_choice(d["correct_key"], d["shown"]) == d["correct_key"]
                    assert engine._parse_choice(f"option {d['correct_key'].lower()}", d["shown"]) == d["correct_key"]
                if d["type"] == "order":
                    assert [next(o["text"] for o in d["shown"] if o["key"] == k) for k in d["correct_order"]] == a["items"]
        print("all activities valid")
    print("SMOKE OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
