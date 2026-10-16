"""FastAPI application: chat API + static chat UI + PDF download.

Sessions are held in memory keyed by a client-generated session id. This is
fine for a single-process demo; swap in Redis or a DB for production.
"""
from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .agent import Agent, AgentState, build_agent
from .documents import generate_pdf
from .forms import get_form, list_forms

app = FastAPI(title="Campus Form Assistant")

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"

# In-memory session store: session_id -> AgentState
_SESSIONS: dict[str, AgentState] = {}
# Cache of generated PDFs: session_id -> (bytes, reference, filename)
_DOCUMENTS: dict[str, tuple[bytes, str, str]] = {}


# --------------------------------------------------------------------------
# API models
# --------------------------------------------------------------------------

class StartRequest(BaseModel):
    form_id: str


class StartResponse(BaseModel):
    session_id: str
    message: str
    progress: list[int]
    done: bool


class ChatRequest(BaseModel):
    session_id: str
    message: str


class ChatResponse(BaseModel):
    message: str
    progress: list[int]
    done: bool
    download_url: str | None = None
    reference: str | None = None


# --------------------------------------------------------------------------
# API routes
# --------------------------------------------------------------------------

@app.get("/api/forms")
def api_forms():
    return {"forms": list_forms()}


@app.post("/api/start", response_model=StartResponse)
def api_start(req: StartRequest):
    agent = build_agent(req.form_id)
    if agent is None:
        raise HTTPException(404, f"Unknown form: {req.form_id}")

    session_id = uuid.uuid4().hex
    _SESSIONS[session_id] = AgentState(form_id=req.form_id)
    reply = agent.greeting()
    return StartResponse(
        session_id=session_id,
        message=reply.message,
        progress=list(reply.progress),
        done=reply.done,
    )


@app.post("/api/chat", response_model=ChatResponse)
def api_chat(req: ChatRequest):
    state = _SESSIONS.get(req.session_id)
    if state is None:
        raise HTTPException(404, "Session not found. Start a new form.")

    agent = build_agent(state.form_id)
    if agent is None:
        raise HTTPException(500, "Form definition missing.")

    reply = agent.handle(state, req.message)

    download_url = None
    reference = None
    if reply.done and reply.result is not None:
        form = get_form(state.form_id)
        pdf_bytes, ref = generate_pdf(form, reply.result)
        filename = f"{form.id}_{ref}.pdf"
        _DOCUMENTS[req.session_id] = (pdf_bytes, ref, filename)
        download_url = f"/api/document/{req.session_id}"
        reference = ref

    return ChatResponse(
        message=reply.message,
        progress=list(reply.progress),
        done=reply.done,
        download_url=download_url,
        reference=reference,
    )


@app.get("/api/document/{session_id}")
def api_document(session_id: str):
    doc = _DOCUMENTS.get(session_id)
    if doc is None:
        raise HTTPException(404, "No document for this session.")
    pdf_bytes, _ref, filename = doc
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# --------------------------------------------------------------------------
# Frontend
# --------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
def index():
    return (STATIC_DIR / "index.html").read_text(encoding="utf-8")


# Mount static assets (css/js) if present.
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
