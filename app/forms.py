"""Data-driven form definitions.

Each form is a declarative schema: an ordered list of fields with types,
prompts, and validation/campus rules. Adding a new form means adding a new
``FormDefinition`` here - no engine code changes required.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Callable, Optional


# --------------------------------------------------------------------------
# Field + rule model
# --------------------------------------------------------------------------

@dataclass
class ValidationResult:
    ok: bool
    message: str = ""
    # A normalized/cleaned value the engine should store instead of raw input.
    normalized: Any = None


# A validator takes (raw_value, collected_so_far) and returns a ValidationResult.
Validator = Callable[[str, dict], ValidationResult]


@dataclass
class Field:
    key: str
    prompt: str
    # Field type drives light client-side formatting + default parsing.
    type: str = "text"  # text | email | number | date | choice | boolean | id
    choices: Optional[list[str]] = None
    help: str = ""
    required: bool = True
    validators: list[Validator] = field(default_factory=list)

    def describe_choices(self) -> str:
        if self.type == "boolean":
            return " (yes/no)"
        if self.choices:
            return " (" + " / ".join(self.choices) + ")"
        return ""


@dataclass
class FormDefinition:
    id: str
    title: str
    description: str
    fields: list[Field]
    # A function that runs AFTER all fields are collected to enforce
    # cross-field campus rules. Returns ValidationResult; on failure the
    # engine points the user back at the offending field key via `normalized`.
    cross_rules: Optional[Callable[[dict], ValidationResult]] = None

    def field_by_key(self, key: str) -> Optional[Field]:
        return next((f for f in self.fields if f.key == key), None)


# --------------------------------------------------------------------------
# Reusable validators
# --------------------------------------------------------------------------

def non_empty(label: str = "a value") -> Validator:
    def _v(raw: str, _ctx: dict) -> ValidationResult:
        if raw and raw.strip():
            return ValidationResult(True, normalized=raw.strip())
        return ValidationResult(False, f"Please provide {label}.")
    return _v


def is_email() -> Validator:
    def _v(raw: str, _ctx: dict) -> ValidationResult:
        raw = (raw or "").strip()
        if "@" in raw and "." in raw.split("@")[-1] and " " not in raw:
            return ValidationResult(True, normalized=raw.lower())
        return ValidationResult(False, "That doesn't look like a valid email address.")
    return _v


def is_campus_email(domain: str) -> Validator:
    def _v(raw: str, _ctx: dict) -> ValidationResult:
        base = is_email()(raw, _ctx)
        if not base.ok:
            return base
        if base.normalized.endswith("@" + domain):
            return ValidationResult(True, normalized=base.normalized)
        return ValidationResult(
            False, f"Please use your campus email ending in @{domain}."
        )
    return _v


def matches_pattern(pattern: str, example: str) -> Validator:
    import re

    rx = re.compile(pattern)

    def _v(raw: str, _ctx: dict) -> ValidationResult:
        raw = (raw or "").strip().upper()
        if rx.fullmatch(raw):
            return ValidationResult(True, normalized=raw)
        return ValidationResult(False, f"Expected a format like {example}.")
    return _v


def is_choice(choices: list[str]) -> Validator:
    lowered = {c.lower(): c for c in choices}

    def _v(raw: str, _ctx: dict) -> ValidationResult:
        key = (raw or "").strip().lower()
        if key in lowered:
            return ValidationResult(True, normalized=lowered[key])
        return ValidationResult(
            False, "Please pick one of: " + ", ".join(choices) + "."
        )
    return _v


def is_boolean() -> Validator:
    yes = {"yes", "y", "true", "1", "yeah", "yep"}
    no = {"no", "n", "false", "0", "nope"}

    def _v(raw: str, _ctx: dict) -> ValidationResult:
        key = (raw or "").strip().lower()
        if key in yes:
            return ValidationResult(True, normalized=True)
        if key in no:
            return ValidationResult(True, normalized=False)
        return ValidationResult(False, "Please answer yes or no.")
    return _v


def is_int_in_range(lo: int, hi: int) -> Validator:
    def _v(raw: str, _ctx: dict) -> ValidationResult:
        try:
            n = int(str(raw).strip())
        except (TypeError, ValueError):
            return ValidationResult(False, "Please enter a whole number.")
        if lo <= n <= hi:
            return ValidationResult(True, normalized=n)
        return ValidationResult(False, f"Please enter a number between {lo} and {hi}.")
    return _v


def is_date_not_past() -> Validator:
    def _v(raw: str, _ctx: dict) -> ValidationResult:
        parsed = _parse_date(raw)
        if parsed is None:
            return ValidationResult(False, "Please use a date like 2026-03-15.")
        if parsed < date.today():
            return ValidationResult(False, "That date is in the past.")
        return ValidationResult(True, normalized=parsed.isoformat())
    return _v


def _parse_date(raw: str) -> Optional[date]:
    raw = (raw or "").strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%B %d, %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


# --------------------------------------------------------------------------
# Campus configuration (the "rules" the agent validates against)
# --------------------------------------------------------------------------

CAMPUS = {
    "name": "California State University",
    "email_domain": "csu.edu",
    # Add/drop deadline for the current term. Real systems would pull this
    # from a term calendar; here it is a single configurable date.
    "add_drop_deadline": date(2026, 11, 30),
    "max_credits": 21,
    "min_credits_full_time": 12,
    "departments": ["Computer Science", "Mathematics", "Biology", "History", "Business"],
}


# --------------------------------------------------------------------------
# Example form: Course Add/Drop Request
# --------------------------------------------------------------------------

def _add_drop_cross_rules(data: dict) -> ValidationResult:
    """Enforce campus rules that depend on more than one field."""
    # Rule: drops after the deadline require an explicit reason.
    deadline = CAMPUS["add_drop_deadline"]
    effective = _parse_date(data.get("effective_date", ""))
    action = data.get("action", "")

    if effective and effective > deadline and action == "Drop":
        if not str(data.get("reason", "")).strip():
            return ValidationResult(
                False,
                f"Drops after the {deadline.isoformat()} deadline need a written "
                "reason for the registrar.",
                normalized="reason",  # field to jump back to
            )

    # Rule: adding a course that pushes you over the credit cap is blocked.
    if action == "Add":
        current = data.get("current_credits", 0)
        adding = data.get("course_credits", 0)
        if isinstance(current, int) and isinstance(adding, int):
            if current + adding > CAMPUS["max_credits"]:
                return ValidationResult(
                    False,
                    f"Adding this course brings you to {current + adding} credits, "
                    f"over the {CAMPUS['max_credits']}-credit limit. Reduce your load "
                    "or request an overload exception first.",
                    normalized="course_credits",
                )

    return ValidationResult(True)


COURSE_ADD_DROP = FormDefinition(
    id="course_add_drop",
    title="Course Add/Drop Request",
    description="Add or drop a course for the current term.",
    fields=[
        Field(
            key="student_name",
            prompt="What's your full name as it appears on your student record?",
            validators=[non_empty("your full name")],
        ),
        Field(
            key="student_id",
            prompt="What's your student ID?",
            type="id",
            help="Format: S followed by 7 digits, e.g. S1234567",
            validators=[matches_pattern(r"S\d{7}", "S1234567")],
        ),
        Field(
            key="email",
            prompt=f"What's your campus email?",
            type="email",
            validators=[is_campus_email(CAMPUS["email_domain"])],
        ),
        Field(
            key="action",
            prompt="Do you want to add or drop a course?",
            type="choice",
            choices=["Add", "Drop"],
            validators=[is_choice(["Add", "Drop"])],
        ),
        Field(
            key="department",
            prompt="Which department offers the course?",
            type="choice",
            choices=CAMPUS["departments"],
            validators=[is_choice(CAMPUS["departments"])],
        ),
        Field(
            key="course_code",
            prompt="What's the course code?",
            help="Format: 2-4 letters, a space, then 3 digits, e.g. CS 101",
            validators=[matches_pattern(r"[A-Z]{2,4} \d{3}", "CS 101")],
        ),
        Field(
            key="course_credits",
            prompt="How many credits is the course?",
            type="number",
            validators=[is_int_in_range(0, 6)],
        ),
        Field(
            key="current_credits",
            prompt="How many credits are you currently enrolled in this term?",
            type="number",
            validators=[is_int_in_range(0, CAMPUS["max_credits"])],
        ),
        Field(
            key="effective_date",
            prompt="What date should this take effect?",
            type="date",
            help="Use a format like 2026-11-15",
            validators=[is_date_not_past()],
        ),
        Field(
            key="reason",
            prompt="Briefly, why are you making this change? (This may be required "
            "for late changes.)",
            required=False,
            validators=[],
        ),
    ],
    cross_rules=_add_drop_cross_rules,
)


# Registry of all available forms, keyed by id.
FORMS: dict[str, FormDefinition] = {
    COURSE_ADD_DROP.id: COURSE_ADD_DROP,
}


def list_forms() -> list[dict]:
    return [
        {"id": f.id, "title": f.title, "description": f.description}
        for f in FORMS.values()
    ]


def get_form(form_id: str) -> Optional[FormDefinition]:
    return FORMS.get(form_id)
