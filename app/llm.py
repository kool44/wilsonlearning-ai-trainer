"""LLM adapter. Two providers: 'anthropic' (Claude) and 'mock' (deterministic, for tests/demo without a key).

The LLM never decides the course sequence. The engine passes it exactly one step at a time and asks for
one of four things: teach, grade, roleplay_reply, grade_roleplay.
"""
from __future__ import annotations

import json
import logging

from . import config

log = logging.getLogger("trainer.llm")

TRAINER_SYSTEM = """You are an expert facilitator delivering Wilson Learning's "The Counselor Salesperson" course,
module "{module_title}", one-to-one with a salesperson, by voice. Everything you say will be read aloud.

Fidelity rules:
- Teach ONLY from the step content provided. Use the course's exact terms and definitions (Relationship Tension,
  Task Tension, Credibility, Empathy, Propriety, Competence, Commonality, Intent, PPP, Ben Duffy, Third-Party Reference).
- Do not invent frameworks, acronyms, statistics, or steps that are not in the provided content.
- If the learner asks something outside this module, answer in one sentence from the glossary if possible, then
  return to the current step.

Voice style:
- Conversational, warm, direct. Short sentences. No bullet symbols, no markdown, no headings. Numbers as words
  where natural. Maximum {max_words} words.
- Finish by asking the step's question, in a natural way but keeping its substance.

Glossary:
{glossary}
"""

GRADER_SYSTEM = """You are the assessor for Wilson Learning's "The Counselor Salesperson", module "{module_title}".
Score the learner's answer against the rubric. One point per rubric item that is clearly met. Be fair but not lenient:
vague or generic answers do not earn points. Feedback is spoken aloud to the learner, so write it as warm, direct speech,
60 to 120 words, no bullets or markdown. Name what they got right, then what was missing, using the course's exact terms.
If this is not their last attempt and they missed items, end with a short nudge toward the missing item without giving
the model answer away. If it is their last attempt, briefly state the model answer's key idea.
"""

CUSTOMER_SYSTEM = """You are role-playing a customer in a sales-training simulation. Stay fully in character.
Never coach, never mention training, never break character, never narrate stage directions.
Reply in one to four spoken sentences, the way a busy executive talks. React realistically to how well the salesperson
demonstrates clear intent, a previewed agenda, understanding of your concerns, and knowledge of your business.

Character:
Name: {name}
Role: {role}
Situation: {situation}
Behavior: {behavior}
"""

BEATS_SCHEMA = {
    "type": "object",
    "properties": {"beats": {"type": "array", "items": {"type": "string"}}},
    "required": ["beats"],
    "additionalProperties": False,
}

BEATS_INSTRUCTIONS = """Deliver this step as a live facilitator talking, not a lecture. Split it into 3 to 6 short spoken
"beats". Each beat is one idea, 20 to 45 words, said the way you would say it across a table. Where natural, end a beat
with a quick check-in such as "Make sense?" or "With me so far?" or a tiny question the learner can answer in a word,
but no more than two of those in total. Cover every teach point. The LAST beat must be the step's question to the learner,
asked naturally. Never use lists or markdown inside a beat. Address the learner by name once, early, only if a name is given."""

QA_INSTRUCTIONS = """The learner interrupted the lesson with a question or comment. Answer it in at most 60 spoken words,
using only the step content and glossary. If it is outside this module, say so in one sentence. Then say you'll pick
the lesson back up. Do not re-teach what you already covered."""

GRADE_SCHEMA = {
    "type": "object",
    "properties": {
        "score": {"type": "integer"},
        "met": {"type": "array", "items": {"type": "string"}},
        "missed": {"type": "array", "items": {"type": "string"}},
        "feedback": {"type": "string"},
    },
    "required": ["score", "met", "missed", "feedback"],
    "additionalProperties": False,
}


def _glossary_text(module: dict) -> str:
    return "\n".join(f"- {k}: {v}" for k, v in module.get("glossary", {}).items())


# ---------------------------------------------------------------- Anthropic
class AnthropicProvider:
    def __init__(self) -> None:
        import anthropic

        self._anthropic = anthropic
        self.client = anthropic.Anthropic()
        self.model = config.MODEL
        self.use_fallbacks = config.USE_FALLBACKS

    def _create(self, *, system: str, messages: list[dict], effort: str, max_tokens: int,
                output_schema: dict | None = None):
        kwargs = dict(
            model=self.model,
            max_tokens=max_tokens,
            system=system,
            messages=messages,
            output_config={"effort": effort},
        )
        if output_schema is not None:
            kwargs["output_config"]["format"] = {"type": "json_schema", "schema": output_schema}
        if self.use_fallbacks:
            try:
                return self.client.beta.messages.create(
                    betas=["server-side-fallback-2026-07-01"], fallbacks="default", **kwargs
                )
            except (self._anthropic.BadRequestError, TypeError) as e:
                if "fallback" not in str(e).lower():
                    raise
                log.warning("fallbacks unsupported here, retrying without: %s", e)
                self.use_fallbacks = False
        return self.client.messages.create(**kwargs)

    @staticmethod
    def _text(resp) -> str:
        if resp.stop_reason == "refusal":
            return ""
        return "".join(b.text for b in resp.content if b.type == "text").strip()

    def teach_beats(self, module: dict, step: dict, learner_name: str | None, attempt_note: str | None) -> list[str]:
        system = TRAINER_SYSTEM.format(
            module_title=module["title"], max_words=300, glossary=_glossary_text(module)
        )
        content = {
            "step_title": step["title"],
            "step_type": step["type"],
            "teach_points": step.get("teach_points", []),
            "question_to_ask": step.get("question"),
        }
        who = f"Learner's name: {learner_name}." if learner_name else "Learner's name unknown: do not invent one, address them as 'you'."
        user = (
            f"{who}\n{BEATS_INSTRUCTIONS}\n"
            f"{json.dumps(content, ensure_ascii=False, indent=1)}"
        )
        if attempt_note:
            user += f"\n\nContext: {attempt_note}"
        resp = self._create(system=system, messages=[{"role": "user", "content": user}],
                            effort=config.TEACH_EFFORT, max_tokens=2500, output_schema=BEATS_SCHEMA)
        try:
            beats = [b.strip() for b in json.loads(self._text(resp))["beats"] if b.strip()]
        except (json.JSONDecodeError, KeyError, TypeError):
            beats = []
        return beats or _fallback_beats(step)

    def answer_question(self, module: dict, step: dict, question: str, covered: list[str]) -> str:
        system = TRAINER_SYSTEM.format(module_title=module["title"], max_words=70, glossary=_glossary_text(module))
        payload = {"task": QA_INSTRUCTIONS, "step_title": step["title"], "teach_points": step.get("teach_points", []),
                   "already_said": covered, "learner_said": question}
        resp = self._create(system=system,
                            messages=[{"role": "user", "content": json.dumps(payload, ensure_ascii=False, indent=1)}],
                            effort="low", max_tokens=500)
        return self._text(resp) or "Good question. Let's keep going and it should become clear."

    def grade(self, module: dict, step: dict, answer: str, attempt: int, last_attempt: bool) -> dict:
        system = GRADER_SYSTEM.format(module_title=module["title"])
        payload = {
            "step_title": step["title"],
            "question": step.get("question"),
            "rubric": step["rubric"],
            "model_answer": step.get("model_answer"),
            "attempt_number": attempt,
            "last_attempt": last_attempt,
            "learner_answer": answer,
        }
        resp = self._create(system=system,
                            messages=[{"role": "user", "content": json.dumps(payload, ensure_ascii=False, indent=1)}],
                            effort=config.GRADE_EFFORT, max_tokens=1500, output_schema=GRADE_SCHEMA)
        return _parse_grade(self._text(resp), len(step["rubric"]))

    def roleplay_reply(self, module: dict, step: dict, transcript: list[dict]) -> str:
        p = step["persona"]
        system = CUSTOMER_SYSTEM.format(**p)
        messages = _transcript_to_messages(transcript)
        if not messages:
            messages = [{"role": "user", "content": "(The salesperson walks in and the meeting begins. Greet them briefly, guarded.)"}]
        resp = self._create(system=system, messages=messages, effort="low", max_tokens=600)
        return self._text(resp) or "Go ahead, I'm listening."

    def hint(self, module: dict, step: dict, transcript: list[dict]) -> str:
        """'Teach me' mode: step out of character, give a short coaching hint, invite the learner to resume."""
        system = TRAINER_SYSTEM.format(module_title=module["title"], max_words=110, glossary=_glossary_text(module))
        payload = {
            "task": "The learner is stuck mid role-play and asked for help. Speak as the facilitator, not the customer. "
                    "In at most 110 words: say what the protocol step they should do next is, give one example sentence "
                    "they could say, then tell them the customer is waiting and to carry on. Do not grade them.",
            "customer": step["persona"]["name"] + ", " + step["persona"]["role"],
            "rubric": step["rubric"],
            "model_answer": step.get("model_answer"),
            "transcript_so_far": [{"speaker": t["role"], "text": t["text"]} for t in transcript],
        }
        resp = self._create(system=system,
                            messages=[{"role": "user", "content": json.dumps(payload, ensure_ascii=False, indent=1)}],
                            effort="low", max_tokens=600)
        return self._text(resp) or "Try opening with your Purpose, Process and Payoff, then check whether that works for her."

    def grade_roleplay(self, module: dict, step: dict, transcript: list[dict]) -> dict:
        system = GRADER_SYSTEM.format(module_title=module["title"])
        payload = {
            "step_title": step["title"],
            "task": "Assess only the SALESPERSON's lines in this role-play transcript against the rubric.",
            "rubric": step["rubric"],
            "model_answer": step.get("model_answer"),
            "attempt_number": 1,
            "last_attempt": True,
            "transcript": [{"speaker": t["role"], "text": t["text"]} for t in transcript],
        }
        resp = self._create(system=system,
                            messages=[{"role": "user", "content": json.dumps(payload, ensure_ascii=False, indent=1)}],
                            effort=config.GRADE_EFFORT, max_tokens=2000, output_schema=GRADE_SCHEMA)
        return _parse_grade(self._text(resp), len(step["rubric"]))


def _transcript_to_messages(transcript: list[dict]) -> list[dict]:
    """Salesperson lines -> user, customer lines -> assistant. Must start with user and alternate."""
    msgs: list[dict] = []
    for t in transcript:
        role = "user" if t["role"] == "salesperson" else "assistant"
        if msgs and msgs[-1]["role"] == role:
            msgs[-1]["content"] += "\n" + t["text"]
        else:
            msgs.append({"role": role, "content": t["text"]})
    if msgs and msgs[0]["role"] == "assistant":
        msgs.insert(0, {"role": "user", "content": "(The salesperson arrives for the meeting.)"})
    return msgs


def _parse_grade(text: str, rubric_len: int) -> dict:
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        log.error("grader returned non-JSON: %r", text[:200])
        data = {"score": 0, "met": [], "missed": [], "feedback": text or "I could not assess that. Let's try once more."}
    data["score"] = max(0, min(int(data.get("score", 0)), rubric_len))
    data["max_score"] = rubric_len
    return data


def _fallback_beats(step: dict) -> list[str]:
    pts = step.get("teach_points", [])
    beats, cur = [], ""
    for p in pts:
        if cur and len((cur + " " + p).split()) > 45:
            beats.append(cur); cur = p
        else:
            cur = (cur + " " + p).strip()
    if cur:
        beats.append(cur)
    if step.get("question"):
        beats.append(step["question"])
    return beats


def _fallback_teach(step: dict) -> str:
    pts = " ".join(step.get("teach_points", []))
    return f"{pts} {step.get('question', '')}".strip()


# --------------------------------------------------------------------- Mock
class MockProvider:
    """Deterministic provider for tests and keyless demos."""

    def teach_beats(self, module, step, learner_name=None, attempt_note=None) -> list[str]:
        return _fallback_beats(step)

    def answer_question(self, module, step, question, covered) -> str:
        return "Mock answer: good question. In short, it comes back to Credibility plus Empathy. Let's pick the lesson back up."

    def grade(self, module, step, answer, attempt, last_attempt) -> dict:
        n = len(step["rubric"])
        words = len(answer.split())
        score = n if words >= 40 else (n - 1 if words >= 15 else 0)
        score = max(0, min(score, n))
        return {
            "score": score, "max_score": n,
            "met": step["rubric"][:score], "missed": step["rubric"][score:],
            "feedback": f"Mock grader: {score} of {n} rubric items met.",
        }

    def roleplay_reply(self, module, step, transcript) -> str:
        n = sum(1 for t in transcript if t["role"] == "salesperson")
        lines = [
            "Hi. I have about thirty minutes. What is this about?",
            "Okay. And what exactly do you want from me today?",
            "Hm. I get a lot of these calls. Why should this one be different?",
            "Alright, go on.",
            "That's fair. What would you do with anything I tell you?",
            "Fine. Let's keep going.",
            "I think we're out of time.",
        ]
        return lines[min(n, len(lines) - 1)]

    def hint(self, module, step, transcript) -> str:
        return ("Mock coach: next, share your Ben Duffy. Try: 'If I were in your shoes I might be wondering whether this "
                "is a pitch. Did I get that right?' The customer is waiting. Carry on.")

    def grade_roleplay(self, module, step, transcript) -> dict:
        n = len(step["rubric"])
        text = " ".join(t["text"].lower() for t in transcript if t["role"] == "salesperson")
        hits = sum(k in text for k in ("purpose", "process", "payoff", "wondering", "sound", "minutes", "shoes", "worked with"))
        score = min(n, hits)
        return {"score": score, "max_score": n, "met": step["rubric"][:score], "missed": step["rubric"][score:],
                "feedback": f"Mock role-play grader: {score} of {n}."}


def get_provider():
    if config.LLM_PROVIDER == "mock":
        return MockProvider()
    return AnthropicProvider()
