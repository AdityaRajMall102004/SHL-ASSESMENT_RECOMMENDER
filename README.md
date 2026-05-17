# SHL Assessment Recommender

An AI-powered conversational agent that helps hiring managers and recruiters find the right **SHL assessments** for any role. Built with **FastAPI**, **FAISS** semantic search, and **HuggingFace Inference API**.

## 🎯 Features

- **Conversational Interface** — Multi-turn dialogue to understand hiring needs
- **Semantic Search** — FAISS vector index over 377 SHL assessments
- **Smart Clarification** — Asks follow-up questions for vague requests
- **Refinement Support** — Modify recommendations mid-conversation
- **Comparison Support** — Compare two assessments from catalog data
- **Scope Guardrails** — Refuses off-topic, legal, and prompt injection queries
- **Catalog-Grounded** — Every recommendation comes from the official SHL catalog

## 🏗️ Architecture

```
┌─────────────┐     ┌──────────────┐     ┌──────────────────┐
│  Frontend   │────▶│  FastAPI      │────▶│  Agent           │
│  (Chat UI)  │◀────│  /health      │◀────│  (prompts.py)    │
│             │     │  /chat        │     │  (retriever.py)  │
└─────────────┘     └──────────────┘     └────────┬─────────┘
                                                   │
                                          ┌────────▼─────────┐
                                          │  HuggingFace     │
                                          │  Inference API   │
                                          │  (Mistral-7B)    │
                                          └──────────────────┘
                                                   │
                                          ┌────────▼─────────┐
                                          │  FAISS Index     │
                                          │  377 assessments │
                                          │  all-MiniLM-L6   │
                                          └──────────────────┘
```

## 📁 Project Structure

```
shl-assessment-recommender/
├── api/
│   └── main.py              # FastAPI service with /health and /chat
├── agent/
│   ├── agent.py             # Core agent logic + LLM calls
│   ├── prompts.py           # System prompt + catalog formatting
│   └── retriever.py         # FAISS semantic search wrapper
├── data/
│   ├── shl_catalog.json     # 377 SHL assessments (scraped)
│   ├── faiss_index.bin      # FAISS vector index
│   ├── retriever.pkl        # Retriever bundle (model + catalog)
│   └── catalog_indexed.json # Catalog with index positions
├── embeddings/
│   └── build_index.py       # Script to build FAISS index
├── scraper/
│   └── scrape_shl_catalog.py # Scraper for SHL product catalog
├── frontend/
│   └── index.html           # Chat web UI
├── tests/
│   ├── evaluate_traces.py   # Recall@10 evaluator + behavior probes
│   ├── convert_traces.py    # Convert .md traces to .json
│   └── traces/              # 10 public conversation traces
├── test_api.py              # Quick API test script
├── requirements.txt         # Python dependencies
├── Procfile                 # Render/Heroku deployment
├── .env                     # API keys (HF_TOKEN)
└── README.md                # This file
```

## 🚀 Quick Start

### 1. Clone & Setup

```bash
cd shl-assessment-recommender
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure API Key

Create a `.env` file:
```
HF_TOKEN=hf_your_huggingface_token_here
```

Get a free token at: https://huggingface.co/settings/tokens

### 3. Build Vector Index (if needed)

```bash
cd embeddings
python build_index.py
cd ..
```

### 4. Start the Server

```bash
uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload
```

### 5. Test

```bash
# Health check
curl http://localhost:8000/health

# Chat
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"messages": [{"role": "user", "content": "I need to hire a Java developer"}]}'

# Run all tests
python test_api.py

# Run behavior probes
python tests/evaluate_traces.py --probes-only

# Run full evaluation with traces
python tests/evaluate_traces.py
```

### 6. Web UI

Open `frontend/index.html` in a browser, or visit `http://localhost:8000` when running the server.

## 📡 API Endpoints

### `GET /health`
Returns `{"status": "ok"}` when the service is ready.

### `POST /chat`
Stateless conversational endpoint.

**Request:**
```json
{
  "messages": [
    {"role": "user", "content": "I am hiring a mid-level Java developer"},
    {"role": "assistant", "content": "Here are some assessments..."},
    {"role": "user", "content": "Also add a personality test"}
  ]
}
```

**Response:**
```json
{
  "reply": "Updated! Here are the assessments for a Java developer with personality fit:",
  "recommendations": [
    {
      "name": "Java 8 (New)",
      "url": "https://www.shl.com/products/product-catalog/view/java-8-new/",
      "test_type": "K"
    },
    {
      "name": "OPQ32r",
      "url": "https://www.shl.com/products/product-catalog/view/occupational-personality-questionnaire-opq32r/",
      "test_type": "P"
    }
  ],
  "end_of_conversation": false
}
```

## 🧪 Evaluation

The agent is evaluated on:

1. **Recall@10** — How many of the expected assessments appear in the agent's top-10 recommendations
2. **Behavior Probes** — 8 automated tests for:
   - Vague query → clarify (no recommendations)
   - Clear query → recommend
   - Off-topic → refuse
   - Prompt injection → refuse
   - URL correctness (shl.com only)
   - Schema compliance
   - Refinement support
   - Job description handling

## 🛠️ Tech Stack

| Component | Technology |
|-----------|-----------|
| Backend | FastAPI + Uvicorn |
| LLM | HuggingFace Inference API (Mistral-7B / Zephyr / Phi-3) |
| Embeddings | SentenceTransformers (all-MiniLM-L6-v2) |
| Vector Search | FAISS (cosine similarity) |
| Frontend | Vanilla HTML/CSS/JS |
| Deployment | Render / Heroku (Procfile) |

## 📄 License

This project is an assignment submission for SHL's assessment recommender challenge.
