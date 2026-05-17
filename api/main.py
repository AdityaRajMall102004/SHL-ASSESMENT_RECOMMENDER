"""
Step 6 — FastAPI Service
=========================
Exposes two endpoints:
  GET  /health  → readiness check
  POST /chat    → stateless conversational agent

Goes in: api/main.py

HOW TO RUN:
  cd shl-assessment-recommender
  pip install -r requirements.txt
  uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload

TEST IT:
  curl http://localhost:8000/health

  curl -X POST http://localhost:8000/chat \
    -H "Content-Type: application/json" \
    -d '{"messages": [{"role": "user", "content": "I need to hire a Java developer"}]}'
"""

import sys
import os
import time
import json
from pathlib import Path

from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, field_validator
from typing import List

# ── PATH SETUP ────────────────────────────────────────────────────────────────
# Add project root to path so agent/ modules can be imported
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "agent"))

# ── IMPORT AGENT ──────────────────────────────────────────────────────────────
from agent import run_agent

# ── FASTAPI APP ───────────────────────────────────────────────────────────────

app = FastAPI(
    title="SHL Assessment Recommender",
    description="Conversational agent that recommends SHL assessments for hiring roles.",
    version="1.0.0",
)

# Allow all origins (needed for deployment + evaluator access)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── SERVE FRONTEND ────────────────────────────────────────────────────────────
FRONTEND_DIR = ROOT / "frontend"
if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")

# ── REQUEST / RESPONSE SCHEMAS ────────────────────────────────────────────────

class Message(BaseModel):
    role: str
    content: str

    @field_validator("role")
    @classmethod
    def role_must_be_valid(cls, v):
        if v not in ("user", "assistant"):
            raise ValueError("role must be 'user' or 'assistant'")
        return v

    @field_validator("content")
    @classmethod
    def content_must_not_be_empty(cls, v):
        if not v or not v.strip():
            raise ValueError("content must not be empty")
        return v.strip()


class ChatRequest(BaseModel):
    messages: List[Message]

    @field_validator("messages")
    @classmethod
    def messages_must_not_be_empty(cls, v):
        if not v:
            raise ValueError("messages list must not be empty")
        # Must start with a user message
        if v[0].role != "user":
            raise ValueError("First message must be from user")
        return v


class Recommendation(BaseModel):
    name: str
    url: str
    test_type: str


class ChatResponse(BaseModel):
    reply: str
    recommendations: List[Recommendation]
    end_of_conversation: bool


# ── ENDPOINTS ─────────────────────────────────────────────────────────────────

@app.get("/")
def root():
    """Serve the chat frontend."""
    index_path = ROOT / "frontend" / "index.html"
    if index_path.exists():
        return FileResponse(str(index_path))
    return {"message": "SHL Assessment Recommender API", "docs": "/docs"}


@app.get("/health")
def health():
    """
    Readiness check endpoint.
    Returns 200 OK when the service is ready.
    Required by the SHL evaluator.
    """
    return {"status": "ok"}


@app.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest):
    """
    Main conversational endpoint.

    - Accepts full stateless conversation history
    - Returns agent reply + optional structured recommendations
    - Schema is non-negotiable (evaluated automatically)
    """
    start_time = time.time()

    # Convert Pydantic models to plain dicts for agent
    messages = [
        {"role": m.role, "content": m.content}
        for m in request.messages
    ]

    # Hard limit: 8 turns max (assignment requirement)
    if len(messages) > 8:
        messages = messages[-8:]

    # Run agent
    try:
        result = run_agent(messages)
    except Exception as e:
        print(f"[API] Agent error: {e}")
        raise HTTPException(
            status_code=500,
            detail="Agent encountered an error. Please try again."
        )

    elapsed = time.time() - start_time
    print(f"[API] /chat responded in {elapsed:.2f}s | "
          f"recs={len(result.get('recommendations', []))} | "
          f"end={result.get('end_of_conversation', False)}")

    # Build response — validate schema strictly
    recommendations = []
    for rec in result.get("recommendations", []):
        try:
            recommendations.append(Recommendation(
                name=rec.get("name", ""),
                url=rec.get("url", ""),
                test_type=rec.get("test_type", ""),
            ))
        except Exception:
            continue  # skip malformed recommendations

    return ChatResponse(
        reply=result.get("reply", ""),
        recommendations=recommendations,
        end_of_conversation=bool(result.get("end_of_conversation", False)),
    )


# ── ERROR HANDLERS ────────────────────────────────────────────────────────────

@app.exception_handler(422)
async def validation_error_handler(request: Request, exc):
    """Return clean error messages for validation failures."""
    return JSONResponse(
        status_code=422,
        content={"detail": "Invalid request format. Check messages schema."},
    )


@app.exception_handler(500)
async def internal_error_handler(request: Request, exc):
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error."},
    )


# ── RUN DIRECTLY ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=False,       # set True during development
    )
