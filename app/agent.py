"""Conversational agent engine.

The engine runs a guided, one-question-at-a-time workflow over a
``FormDefinition``. It is deterministic at its core (so the app always works
offline and validation is reliable), and optionally uses an LLM to rephrase
prompts in a warmer, more conversational tone.

Conversation state is intentionally simple and serializable so it can live in
a session store.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field as dc_field
from typing import Any, Optional

from .forms import FormDefinition, ValidationResult, get_form


@dataclass
class AgentState:
    form_id: str
    collected: dict[str, Any] = dc_field(default_factory=dict)
    current_index: int = 0
    done: bool = False

    def to_dict(self) -> dict:
        return {
            "form_id": self.form_id,
            "collected": self.collected,
            "current_index": self.current_index,
            "done": self.done,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "AgentState":
        return cls(
            form_id=d["form_id"],
            collected=dict(d.get("collected", {})),
            current_index=int(d.get("current_index", 0)),
            done=bool(d.get("done", False)),
        )


@dataclass
class AgentReply:
    message: str
    done: bool = False
    # When the form is complete, the fully collected + validated data.
    result: Optional[dict] = None
    # Progress info for the UI.
    progress: tuple[int, int] = (0, 0)


class Agent:
    def __init__(self, form: FormDefinition):
        self.form = form

    # -- lifecycle ----------------------------------------------------------

    def greeting(self) -> AgentReply:
        """First message when a form starts."""
        intro = (
            f"Hi! I'll help you with the {self.form.title}. "
            f"{self.form.description} I'll ask a few questions one at a time, "
            "check everything against campus rules, and then generate a "
            "submission-ready document for you.\n\n"
        )
        first = self.form.fields[0]
        return AgentReply(
            message=intro + _format_prompt(first),
            progress=(0, len(self.form.fields)),
        )

    def handle(self, state: AgentState, user_input: str) -> AgentReply:
        """Process one user message and advance the workflow."""
        if state.done:
            return AgentReply(
                message="This form is already complete. Start a new one anytime.",
                done=True,
                result=state.collected,
                progress=(len(self.form.fields), len(self.form.fields)),
            )

        current = self.form.fields[state.current_index]

        # Allow skipping optional fields.
        if not current.required and _is_skip(user_input):
            state.collected[current.key] = ""
            return self._advance(state)

        result = self._validate_field(current, user_input, state.collected)
        if not result.ok:
            # Stay on the same field, explain the problem.
            return AgentReply(
                message=_rephrase_error(current, result.message),
                progress=(state.current_index, len(self.form.fields)),
            )

        state.collected[current.key] = result.normalized
        return self._advance(state)

    # -- internals ----------------------------------------------------------

    def _validate_field(self, fld, raw: str, ctx: dict) -> ValidationResult:
        if fld.required and not (raw and raw.strip()):
            return ValidationResult(
                False, "This one's required - please provide a value."
            )
        if not fld.required and not (raw and raw.strip()):
            return ValidationResult(True, normalized="")

        # Run each validator in order. The last successful validator's
        # normalized value is what we store, so order validators from least
        # to most specific (e.g. is_email before is_campus_email).
        normalized: Any = raw.strip()
        for v in fld.validators:
            res = v(raw, ctx)
            if not res.ok:
                return res
            if res.normalized is not None:
                normalized = res.normalized
        return ValidationResult(True, normalized=normalized)

    def _advance(self, state: AgentState) -> AgentReply:
        state.current_index += 1

        # All fields collected -> run cross-field campus rules.
        if state.current_index >= len(self.form.fields):
            if self.form.cross_rules:
                cross = self.form.cross_rules(state.collected)
                if not cross.ok:
                    # Jump back to the offending field.
                    bad_key = cross.normalized
                    idx = next(
                        (i for i, f in enumerate(self.form.fields) if f.key == bad_key),
                        None,
                    )
                    if idx is not None:
                        state.current_index = idx
                        fld = self.form.fields[idx]
                        return AgentReply(
                            message=cross.message
                            + "\n\n"
                            + _format_prompt(fld),
                            progress=(idx, len(self.form.fields)),
                        )
                    return AgentReply(
                        message=cross.message,
                        progress=(
                            len(self.form.fields),
                            len(self.form.fields),
                        ),
                    )

            # Fully valid.
            state.done = True
            summary = _summarize(self.form, state.collected)
            return AgentReply(
                message=(
                    "All set - everything checks out against campus rules. "
                    "Here's a summary:\n\n"
                    + summary
                    + "\n\nI've generated a submission-ready PDF you can "
                    "download below."
                ),
                done=True,
                result=state.collected,
                progress=(len(self.form.fields), len(self.form.fields)),
            )

        nxt = self.form.fields[state.current_index]
        return AgentReply(
            message=_format_prompt(nxt),
            progress=(state.current_index, len(self.form.fields)),
        )


# --------------------------------------------------------------------------
# Prompt formatting (deterministic, with optional LLM rephrasing)
# --------------------------------------------------------------------------

def _format_prompt(fld) -> str:
    text = fld.prompt + fld.describe_choices()
    if fld.help:
        text += f"\n_{fld.help}_"
    if not fld.required:
        text += "\n(Optional - say 'skip' to leave it blank.)"
    return _maybe_llm_rephrase(text)


def _rephrase_error(fld, message: str) -> str:
    text = message + " " + fld.prompt + fld.describe_choices()
    return _maybe_llm_rephrase(text)


def _is_skip(raw: str) -> bool:
    return (raw or "").strip().lower() in {"skip", "none", "n/a", "na", "-"}


def _summarize(form: FormDefinition, data: dict) -> str:
    lines = []
    for f in form.fields:
        val = data.get(f.key, "")
        if val == "" and not f.required:
            continue
        label = f.key.replace("_", " ").title()
        if isinstance(val, bool):
            val = "Yes" if val else "No"
        lines.append(f"- **{label}:** {val}")
    return "\n".join(lines)


def _maybe_llm_rephrase(text: str) -> str:
    """If an LLM is configured, warm up the phrasing; otherwise return as-is.

    Kept deliberately defensive: any failure falls back to the deterministic
    text so the workflow never breaks.
    """
    if not os.getenv("OPENAI_API_KEY"):
        return text
    try:
        return _llm_rephrase(text)
    except Exception:
        return text


def _llm_rephrase(text: str) -> str:
    import httpx

    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    base = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    resp = httpx.post(
        f"{base}/chat/completions",
        headers={"Authorization": f"Bearer {os.getenv('OPENAI_API_KEY')}"},
        json={
            "model": model,
            "temperature": 0.4,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a friendly campus assistant. Rephrase the "
                        "given prompt to be warm and concise. Keep any "
                        "formatting hints, choices, and required-format "
                        "details intact. Do not add new questions."
                    ),
                },
                {"role": "user", "content": text},
            ],
        },
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"].strip()


def build_agent(form_id: str) -> Optional[Agent]:
    form = get_form(form_id)
    return Agent(form) if form else None
