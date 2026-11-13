"""End-to-end smoke test of the session engine with the mock provider (no API key needed).

Run:  LLM_PROVIDER=mock python -m tests.smoke_session
"""
import os
import sys
import tempfile

os.environ.setdefault("LLM_PROVIDER", "mock")
os.environ.setdefault("DB_PATH", os.path.join(tempfile.mkdtemp(), "t.db"))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

GOOD = ("When a new vendor called me last year the rep opened by explaining exactly why he was calling, how long it "
        "would take, and what I would get out of it, then asked if that worked for me. He had clearly thought about "
        "what I would be worried about, named it before I did, and listened. That raised my comfort fast. "
        "Relationship tension dropped and I was willing to talk about the actual task.")
WEAK = "Not sure, trust is important I guess."


def main() -> int:
    with TestClient(app) as c:
        assert c.get("/api/health").json()["ok"]
        mods = c.get("/api/modules").json()
        assert mods and mods[0]["id"] == "csp-m2-relating", mods
        r = c.post("/api/session", json={"module_id": mods[0]["id"], "learner_name": "Sam"}).json()
        sid = r["session_id"]
        assert r["messages"][0]["kind"] == "teach" and r["messages"][0]["beat"] == 1
        p = r["progress"]; total = p["step_total"]
        print(f"session {sid}, {total} steps, step 1 has {p['beats']} beats")

        # mid-lesson question -> answered, lesson continues
        r = c.post(f"/api/session/{sid}/message", json={"text": "What does No Trust mean exactly?"}).json()
        kinds = [m["kind"] for m in r["messages"]]
        assert kinds == ["answer", "teach"], kinds
        # acks advance beats until the question beat
        while r["progress"]["phase"] == "teaching":
            r = c.post(f"/api/session/{sid}/message", json={"text": "ok go on"}).json()
        assert r["progress"]["phase"] == "asked" and r["messages"][-1]["last_beat"]
        print("beats ok")

        # weak answer -> retry, same step
        r = c.post(f"/api/session/{sid}/message", json={"text": WEAK}).json()
        kinds = [m["kind"] for m in r["messages"]]
        assert kinds == ["feedback", "retry"], kinds
        assert r["progress"]["step_index"] == 0

        # second weak answer -> last attempt, advances with model answer
        r = c.post(f"/api/session/{sid}/message", json={"text": WEAK}).json()
        assert r["progress"]["step_index"] == 1, r["progress"]
        print("retry/advance logic ok")

        # good answers through to the roleplay (ack through each lesson's beats first)
        while r["progress"]["phase"] in ("asked", "teaching"):
            txt = "ok" if r["progress"]["phase"] == "teaching" else GOOD
            r = c.post(f"/api/session/{sid}/message", json={"text": txt}).json()
        assert r["progress"]["phase"] == "roleplay", r["progress"]
        print(f"reached roleplay at step {r['progress']['step_index'] + 1}")

        # roleplay turns
        r = c.post(f"/api/session/{sid}/message", json={"text": "Thanks for the time Maria. The purpose of this meeting is to understand how the reorganization changes your downtime priorities. Process: a few questions you may be wondering about us, then your situation, about 25 minutes. Payoff: you learn if we are worth more time, I learn if we can help. Does that sound ok?"}).json()
        assert r["messages"][0]["kind"] == "customer", r["messages"]
        r = c.post(f"/api/session/{sid}/message", json={"text": "If I were in your shoes I'd wonder whether this is a pitch and what happens to data you share. Did I get those right?"}).json()
        r = c.post(f"/api/session/{sid}/message", json={"text": "end call"}).json()
        kinds = [m["kind"] for m in r["messages"]]
        assert kinds[0] == "feedback" and "score" in r["messages"][0], r["messages"]
        print("roleplay graded:", r["messages"][0]["score"], "/", r["messages"][0]["max_score"])

        # reflection -> complete
        while r["progress"]["phase"] == "teaching":
            r = c.post(f"/api/session/{sid}/message", json={"text": "ok"}).json()
        r = c.post(f"/api/session/{sid}/message", json={"text": GOOD}).json()
        assert r["progress"]["phase"] == "done", r["progress"]
        assert r["messages"][-1]["kind"] == "complete"
        print("module complete:", r["messages"][-1]["text"][:80])

        # resume + commands
        assert c.get(f"/api/session/{sid}").json()["progress"]["phase"] == "done"
        r = c.post(f"/api/session/{sid}/command", json={"cmd": "restart"}).json()
        assert r["progress"]["step_index"] == 0
        r = c.post(f"/api/session/{sid}/command", json={"cmd": "skip"}).json()
        assert r["progress"]["step_index"] == 1
        r = c.post(f"/api/session/{sid}/command", json={"cmd": "repeat"}).json()
        assert r["messages"][0]["kind"] == "teach"
        print("commands ok")
    print("SMOKE OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
