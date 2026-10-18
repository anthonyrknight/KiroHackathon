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


def min_length(min_chars: int, label: str = "more detail") -> Validator:
    def _v(raw: str, _ctx: dict) -> ValidationResult:
        raw = (raw or "").strip()
        if len(raw) >= min_chars:
            return ValidationResult(True, normalized=raw)
        return ValidationResult(
            False,
            f"Please provide {label} - at least {min_chars} characters so the "
            f"committee has enough to review (you wrote {len(raw)}).",
        )
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
    "registrar_office": "Office of the University Registrar",
    "registrar_address": "6000 J Street, Sacramento, CA 95819",
    "registrar_phone": "(916) 278-6011",
    "current_term": "Fall 2026",
}


# --------------------------------------------------------------------------
# Mock student records (the "database" the agent verifies against)
#
# A real system would query a student information system (SIS) over an API.
# Here we use an in-memory dictionary keyed by student ID. Lookups are
# case-insensitive on the ID and cross-check the name + email so the agent
# can only verify a student who matches their own record.
# --------------------------------------------------------------------------

STUDENT_RECORDS: dict[str, dict] = {
    "S1234567": {
        "student_name": "Jordan Rivera",
        "email": "jordan.rivera@csus.edu",
        "enrollment_status": "Full-time",
        "credits_enrolled": 15,
        "program": "B.S. Computer Science",
        "class_standing": "Junior",
        "term": "Fall 2026",
        "expected_graduation": "Spring 2028",
        "enrollment_start": "August 25, 2025",
    },
    "S7654321": {
        "student_name": "Priya Patel",
        "email": "priya.patel@csus.edu",
        "enrollment_status": "Full-time",
        "credits_enrolled": 12,
        "program": "B.A. History",
        "class_standing": "Senior",
        "term": "Fall 2026",
        "expected_graduation": "Fall 2026",
        "enrollment_start": "August 28, 2023",
    },
    "S2468013": {
        "student_name": "Marcus Lee",
        "email": "marcus.lee@csus.edu",
        "enrollment_status": "Part-time",
        "credits_enrolled": 6,
        "program": "B.S. Biology",
        "class_standing": "Sophomore",
        "term": "Fall 2026",
        "expected_graduation": "Spring 2029",
        "enrollment_start": "January 20, 2025",
    },
}


def lookup_student(student_id: str) -> Optional[dict]:
    """Return the student record for an ID, or None if not found."""
    if not student_id:
        return None
    return STUDENT_RECORDS.get(student_id.strip().upper())


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


# --------------------------------------------------------------------------
# Enrollment Verification Letter
#
# A student needs proof of enrollment (e.g. for a landlord). The agent
# collects their identifying details, validates them against the student
# database, and - only on a match - generates a completed verification
# letter addressed to the requested recipient.
# --------------------------------------------------------------------------

def _enrollment_cross_rules(data: dict) -> ValidationResult:
    """Verify the provided identity against the student database.

    This is the heart of the workflow: the collected name + email must match
    the record on file for the given student ID. On a match we enrich the
    collected data with the official record so the letter is authoritative.
    """
    student_id = str(data.get("student_id", "")).strip().upper()
    record = lookup_student(student_id)

    if record is None:
        return ValidationResult(
            False,
            "I couldn't find a student record for that ID. Double-check your "
            "student ID and try again.",
            normalized="student_id",
        )

    # Name must match (case-insensitive, whitespace-tolerant).
    given_name = str(data.get("student_name", "")).strip().lower()
    if given_name != record["student_name"].strip().lower():
        return ValidationResult(
            False,
            "The name you entered doesn't match the record on file for that "
            "student ID. Please enter your full legal name exactly as it "
            "appears on your student record.",
            normalized="student_name",
        )

    # Email must match the record.
    given_email = str(data.get("email", "")).strip().lower()
    if given_email != record["email"].strip().lower():
        return ValidationResult(
            False,
            "The campus email you entered doesn't match the record on file "
            "for that student ID. Please use the email tied to your account.",
            normalized="email",
        )

    # Verified. Enrich the collected data with authoritative record fields so
    # the generated letter reflects official information, not user claims.
    data["verified"] = True
    data["enrollment_status"] = record["enrollment_status"]
    data["credits_enrolled"] = record["credits_enrolled"]
    data["program"] = record["program"]
    data["class_standing"] = record["class_standing"]
    data["term"] = record["term"]
    data["expected_graduation"] = record["expected_graduation"]
    data["enrollment_start"] = record["enrollment_start"]

    return ValidationResult(True)


ENROLLMENT_VERIFICATION = FormDefinition(
    id="enrollment_verification",
    title="Enrollment Verification Letter",
    description="Request an official letter confirming your enrollment, e.g. "
    "for a landlord, employer, or bank.",
    fields=[
        Field(
            key="student_name",
            prompt="What's your full legal name as it appears on your student record?",
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
            prompt="What's your campus email?",
            type="email",
            validators=[is_campus_email(CAMPUS["email_domain"])],
        ),
        Field(
            key="recipient_name",
            prompt="Who should the letter be addressed to?",
            help="For example your landlord's name or property management company.",
            validators=[non_empty("the recipient's name")],
        ),
        Field(
            key="purpose",
            prompt="What's the letter for?",
            type="choice",
            choices=["Housing / Landlord", "Employer", "Bank / Loan", "Insurance", "Other"],
            validators=[is_choice(
                ["Housing / Landlord", "Employer", "Bank / Loan", "Insurance", "Other"]
            )],
        ),
    ],
    cross_rules=_enrollment_cross_rules,
)


# --------------------------------------------------------------------------
# Satisfactory Academic Progress (SAP) Appeal
#
# A student who has lost financial aid eligibility (failed GPA, failed pace /
# completion rate, or exceeded the maximum timeframe) can appeal to have aid
# reinstated. A strong appeal needs: the standard(s) failed, the extenuating
# circumstance that caused it, a personal statement explaining what happened
# and what has changed, and a concrete academic plan going forward. The agent
# guides the student through each piece and enforces that the required
# supporting pieces are present before generating the completed appeal.
# --------------------------------------------------------------------------

# Circumstances that the committee expects supporting documentation for.
SAP_DOC_REQUIRED = {
    "Medical / health",
    "Death of a family member",
    "Mental health",
}

SAP_CIRCUMSTANCES = [
    "Medical / health",
    "Mental health",
    "Death of a family member",
    "Family emergency",
    "Financial hardship",
    "Military service",
    "Other",
]

SAP_STANDARDS = [
    "GPA below 2.0",
    "Pace / completion rate below 67%",
    "Exceeded maximum timeframe",
    "Multiple of the above",
]


def _sap_cross_rules(data: dict) -> ValidationResult:
    """Enforce that documentation is acknowledged where the committee requires it."""
    circumstance = data.get("circumstance", "")
    documentation = data.get("has_documentation")

    if circumstance in SAP_DOC_REQUIRED and documentation is False:
        return ValidationResult(
            False,
            f"Appeals citing \"{circumstance}\" must include supporting "
            "documentation (for example a doctor's note, hospital record, or "
            "death certificate). The committee cannot approve this type of "
            "appeal without it. Please confirm you can attach documentation, "
            "or choose the circumstance that best fits your situation.",
            normalized="has_documentation",
        )

    return ValidationResult(True)


SAP_APPEAL = FormDefinition(
    id="sap_appeal",
    title="Financial Aid SAP Appeal",
    description="Appeal a loss of financial aid eligibility due to Satisfactory "
    "Academic Progress (SAP). The assistant guides you through each required piece.",
    fields=[
        Field(
            key="student_name",
            prompt="What's your full legal name as it appears on your student record?",
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
            prompt="What's your campus email?",
            type="email",
            validators=[is_campus_email(CAMPUS["email_domain"])],
        ),
        Field(
            key="standard_failed",
            prompt="Which SAP standard were you flagged for? If you're not sure, "
            "check your financial aid notice.",
            type="choice",
            choices=SAP_STANDARDS,
            validators=[is_choice(SAP_STANDARDS)],
        ),
        Field(
            key="term_affected",
            prompt="Which term did the difficulty occur in?",
            help="For example: Spring 2026",
            validators=[non_empty("the affected term")],
        ),
        Field(
            key="circumstance",
            prompt="What was the main extenuating circumstance behind it?",
            type="choice",
            choices=SAP_CIRCUMSTANCES,
            validators=[is_choice(SAP_CIRCUMSTANCES)],
        ),
        Field(
            key="has_documentation",
            prompt="Can you attach supporting documentation for that circumstance?",
            type="boolean",
            help="For example a doctor's note, hospital record, or official letter.",
            validators=[is_boolean()],
        ),
        Field(
            key="personal_statement",
            prompt="In your own words, explain what happened: what prevented you "
            "from meeting the standard, and when. Be specific and honest.",
            help="This is the heart of your appeal. Aim for a few sentences.",
            validators=[min_length(120, "a thorough explanation of what happened")],
        ),
        Field(
            key="whats_changed",
            prompt="What has changed now so you can succeed going forward?",
            help="For example: the situation has resolved, you've set up support, "
            "reduced your course load, etc.",
            validators=[min_length(80, "a clear description of what has changed")],
        ),
        Field(
            key="academic_plan",
            prompt="What's your concrete academic plan to get back on track?",
            help="For example: specific courses, credit load, tutoring, advisor "
            "meetings, or a target GPA.",
            validators=[min_length(80, "a concrete plan")],
        ),
    ],
    cross_rules=_sap_cross_rules,
)


# Registry of all available forms, keyed by id.
FORMS: dict[str, FormDefinition] = {
    COURSE_ADD_DROP.id: COURSE_ADD_DROP,
    ENROLLMENT_VERIFICATION.id: ENROLLMENT_VERIFICATION,
    SAP_APPEAL.id: SAP_APPEAL,
}


def list_forms() -> list[dict]:
    return [
        {"id": f.id, "title": f.title, "description": f.description}
        for f in FORMS.values()
    ]


def get_form(form_id: str) -> Optional[FormDefinition]:
    return FORMS.get(form_id)
