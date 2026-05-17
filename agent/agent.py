"""
STEP 5 — agent/agent.py
=========================
Core agent logic using Groq (primary) and HuggingFace (fallback).

SETUP:
  1. Get free Groq key: https://console.groq.com/keys
  2. Add to .env:  GROQ_API_KEY=gsk_xxxxxxxxxxxx
  3. pip install groq huggingface_hub python-dotenv
"""

import os
import json
import re
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ── CONFIG ────────────────────────────────────────────────────────────────────

DATA_DIR     = Path(__file__).parent.parent / "data"
CATALOG_PATH = DATA_DIR / "shl_catalog.json"

# Groq models — fast, free tier
GROQ_MODELS = [
    "llama-3.3-70b-versatile",
    "llama-3.1-8b-instant",
    "meta-llama/llama-4-scout-17b-16e-instruct",
]

# HuggingFace fallback models
HF_MODELS = [
    "mistralai/Mistral-7B-Instruct-v0.3",
    "HuggingFaceH4/zephyr-7b-beta",
    "microsoft/Phi-3-mini-4k-instruct",
]

MAX_TOKENS       = 1500
TEMPERATURE      = 0.1
TOP_K_RETRIEVE   = 20
MAX_CLARIFY_TURNS = 1

# ── STARTUP — load once at import time ───────────────────────────────────────

def _load_catalog() -> list:
    with open(CATALOG_PATH, encoding="utf-8") as f:
        return json.load(f)

def _load_retriever():
    from retriever import get_retriever
    return get_retriever()

print("[Agent] Loading catalog...")
CATALOG = _load_catalog()
print(f"[Agent] Loaded {len(CATALOG)} assessments")

from prompts import build_system_prompt_base, format_catalog_for_prompt

print("[Agent] Loading FAISS retriever...")
RETRIEVER = _load_retriever()
print("[Agent] Ready.\n")

# ── HELPERS ───────────────────────────────────────────────────────────────────

def count_assistant_turns(messages: list) -> int:
    return sum(1 for m in messages if m.get("role") == "assistant")


def is_vague(messages: list) -> bool:
    """
    Returns True if the conversation so far is too vague to recommend.
    Vague = no specific role, no job description, no skill mentioned.
    """
    if not messages:
        return True

    # Combine ALL user messages (not just first)
    all_user_text = " ".join(
        m["content"] for m in messages if m.get("role") == "user"
    ).lower()

    # Very short = definitely vague
    if len(all_user_text.split()) < 5:
        return True

    # Generic assessment requests with no role context
    vague_patterns = [
        "i need an assessment",
        "i need assessment",
        "need a test",
        "need some tests",
        "help me hire",
        "what tests do you have",
        "what assessments",
        "show me assessments",
        "recommend something",
        "give me assessment",
    ]
    if any(p in all_user_text for p in vague_patterns) and len(all_user_text.split()) < 8:
        return True

    # Must contain at least one role/skill/context indicator
    role_indicators = [
        "developer", "engineer", "manager", "analyst", "designer",
        "sales", "marketing", "finance", "java", "python", "sql", "c++",
        "hire", "hiring", "recruit", "position", "role",
        "senior", "junior", "mid-level", "entry", "graduate", "lead",
        "job description", "jd:", "looking for", "we need",
        "data", "software", "product", "operations", "customer service",
        "accountant", "nurse", "teacher", "driver", "technician",
        "programmer", "architect", "consultant", "specialist", "coordinator",
        "supervisor", "director", "executive", "officer", "associate",
        "contact centre", "contact center", "admin", "plant", "operator",
        "leadership", "trainee", "healthcare", "safety",
    ]
    return not any(kw in all_user_text for kw in role_indicators)


def retrieve_relevant(messages: list) -> list:
    query = " ".join(
        m["content"] for m in messages[-4:]
        if m.get("role") == "user" and m.get("content")
    )
    return RETRIEVER.search(query, top_k=TOP_K_RETRIEVE)


def build_context_prompt(messages: list) -> str:
    """
    Always uses FAISS retrieval to keep prompt within Groq free tier limits.
    Gets top-20 relevant assessments based on conversation context.
    """
    relevant = retrieve_relevant(messages)
    relevant_text = format_catalog_for_prompt(relevant, max_items=TOP_K_RETRIEVE)
    return build_system_prompt_base(relevant_text)


# ── JSON RESPONSE PARSER ──────────────────────────────────────────────────────

def parse_response(raw_text: str) -> dict:
    default = {
        "reply": "I encountered an issue. Could you rephrase your request?",
        "recommendations": [],
        "end_of_conversation": False,
    }
    if not raw_text or not raw_text.strip():
        return default

    text = raw_text.strip()
    text = re.sub(r"```json\s*", "", text)
    text = re.sub(r"```\s*", "", text)
    text = text.strip()

    # Extract JSON object
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        text = match.group(0)

    # Fix trailing commas
    text = re.sub(r",\s*([}\]])", r"\1", text)

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        try:
            data = json.loads(text, strict=False)
        except Exception:
            return default

    result = {
        "reply": str(data.get("reply", default["reply"])).strip(),
        "recommendations": [],
        "end_of_conversation": bool(data.get("end_of_conversation", False)),
    }

    for rec in data.get("recommendations", []):
        if not isinstance(rec, dict):
            continue
        name  = str(rec.get("name", "")).strip()
        url   = str(rec.get("url", "")).strip()
        ttype = str(rec.get("test_type", "")).strip()

        if not name or not url:
            continue
        if not url.startswith("https://www.shl.com"):
            continue

        # Validate against catalog — exact match first, then fuzzy
        catalog_match = next(
            (a for a in CATALOG if a.get("name", "").lower() == name.lower()), None
        )
        if not catalog_match:
            catalog_match = next(
                (a for a in CATALOG
                 if name.lower() in a.get("name", "").lower()
                 or a.get("name", "").lower() in name.lower()), None
            )
        if catalog_match:
            result["recommendations"].append({
                "name":      catalog_match["name"],
                "url":       catalog_match["url"],
                "test_type": catalog_match.get("test_type_codes", ttype),
            })

    result["recommendations"] = result["recommendations"][:10]
    return result


# ── LLM CALL ─────────────────────────────────────────────────────────────────

def call_groq(system: str, messages: list) -> str:
    """Call Groq API (primary — fast and free)."""
    from groq import Groq

    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY not set")

    client = Groq(api_key=api_key)

    groq_messages = [{"role": "system", "content": system}]
    for m in messages:
        groq_messages.append({"role": m["role"], "content": m["content"]})

    for model in GROQ_MODELS:
        try:
            response = client.chat.completions.create(
                model=model,
                messages=groq_messages,
                max_tokens=MAX_TOKENS,
                temperature=TEMPERATURE,
                response_format={"type": "json_object"},
            )
            raw = response.choices[0].message.content
            print(f"[Agent] LLM: Groq/{model}")
            return raw
        except Exception as e:
            print(f"[Agent] Groq/{model} failed: {e}")
            continue

    raise RuntimeError("All Groq models failed")


def call_hf(system: str, messages: list) -> str:
    """Call HuggingFace Inference API (fallback)."""
    from huggingface_hub import InferenceClient

    hf_messages = [{"role": "system", "content": system}]
    for m in messages:
        hf_messages.append({"role": m["role"], "content": m["content"]})

    for model in HF_MODELS:
        try:
            client = InferenceClient(
                model=model,
                token=os.environ.get("HF_TOKEN"),
            )
            response = client.chat_completion(
                messages=hf_messages,
                max_tokens=MAX_TOKENS,
                temperature=TEMPERATURE,
            )
            raw = response.choices[0].message.content
            print(f"[Agent] LLM: HF/{model}")
            return raw
        except Exception as e:
            print(f"[Agent] HF/{model} failed: {e}")
            continue

    raise RuntimeError("All HF models failed")


def call_llm(system: str, messages: list) -> str:
    """Try Groq first, then HuggingFace as fallback."""
    # Try Groq first (faster, more reliable)
    try:
        return call_groq(system, messages)
    except Exception as e:
        print(f"[Agent] Groq backend failed: {e}")

    # Fallback to HuggingFace
    try:
        return call_hf(system, messages)
    except Exception as e:
        print(f"[Agent] HF backend failed: {e}")

    raise RuntimeError("All LLM backends failed. Check API keys.")


# ── MAIN ENTRY POINT ──────────────────────────────────────────────────────────

def run_agent(messages: list) -> dict:
    """
    Called by FastAPI for every /chat request.

    Args:
        messages: Full conversation history
                  [{"role": "user"/"assistant", "content": "..."}]

    Returns:
        {"reply": "...", "recommendations": [...], "end_of_conversation": bool}
    """
    if not messages:
        return {
            "reply": "Hello! I help find the right SHL assessments for your hiring needs. What role are you hiring for?",
            "recommendations": [],
            "end_of_conversation": False,
        }

    total_turns = len(messages)

    # Force recommendation on last allowed turn
    force_hint = ""
    if total_turns >= 7:
        force_hint = (
            "\n\nCRITICAL: This is the FINAL turn. "
            "You MUST provide recommendations now based on all context so far. "
            "Do NOT ask any more questions. Respond in JSON with recommendations."
        )

    # JSON reminder
    json_hint = "\n\nREMINDER: Respond ONLY with valid JSON. No text outside the JSON object."

    system = build_context_prompt(messages) + force_hint + json_hint

    try:
        raw_text = call_llm(system, messages)
    except Exception as e:
        print(f"[Agent] LLM call failed: {e}")
        return {
            "reply": "I am having trouble connecting. Please try again in a moment.",
            "recommendations": [],
            "end_of_conversation": False,
        }

    result = parse_response(raw_text)

    # Safety: never recommend if query is still vague
    # Applies to turn 0 AND turn 1 (first two clarifying turns)
    assistant_turns = count_assistant_turns(messages)
    if assistant_turns <= 1 and is_vague(messages):
        result["recommendations"] = []

    print(f"[Agent] Turn {total_turns}: recs={len(result['recommendations'])} end={result['end_of_conversation']}")
    return result
