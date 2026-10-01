# Ledger — AI Quality & Compliance Intelligence Agent

An agent that continuously checks company processes and documents against
internal policies and compliance requirements. It uses RAG and a reasoning
agent to retrieve policies, analyze organizational records, and identify
potential compliance gaps.

**Pipeline:** Document Processing → RAG → Policy Analysis → Compliance Reasoning → Risk Report
**Stack:** LLM (Claude) · RAG (ChromaDB vector DB + sentence-transformers) · NLP · FastAPI backend · plain HTML/CSS/JS frontend (no Streamlit)

---

## 1. Project structure

```
ai-compliance-agent/
├── backend/
│   ├── main.py                 FastAPI app + all REST endpoints, serves the frontend
│   ├── config.py                Paths, model names, chunking settings
│   ├── models.py                Pydantic schemas
│   ├── document_processor.py    PDF/DOCX/TXT extraction + chunking
│   ├── rag_engine.py            Embeddings + ChromaDB vector store + retrieval
│   ├── compliance_agent.py      Policy analysis, compliance reasoning, risk report generation (Claude)
│   ├── requirements.txt
│   └── data/                    Created automatically: uploads, vector store, reports
├── frontend/
│   ├── index.html               Single-page web app (Dashboard / Policies / Documents / Reports / Ask)
│   ├── style.css
│   └── app.js
└── README.md
```

## 2. Requirements

- Python 3.10+
- An Anthropic API key ([console.anthropic.com](https://console.anthropic.com))

## 3. Setup (VS Code)

1. Open the `ai-compliance-agent` folder in VS Code.
2. Open a terminal (`` Ctrl+` ``) and create a virtual environment:

   ```bash
   cd backend
   python -m venv venv
   source venv/bin/activate        # Windows: venv\Scripts\activate
   pip install -r requirements.txt
   ```

3. Set your API key for this terminal session:

   ```bash
   export ANTHROPIC_API_KEY="sk-ant-your-key-here"   # Windows (PowerShell): $env:ANTHROPIC_API_KEY="sk-ant-..."
   ```

   Or create a `.env` file and use `python-dotenv` / your shell profile — anything that ends up setting the `ANTHROPIC_API_KEY` environment variable before `uvicorn` starts.

4. Run the backend:

   ```bash
   uvicorn main:app --reload --port 8000
   ```

5. Open **http://localhost:8000** in your browser. That's it — FastAPI serves the plain HTML/CSS/JS frontend directly, so there's no separate frontend server or build step.

The first run will download the local embedding model (`all-MiniLM-L6-v2`, ~90MB) from Hugging Face — this needs internet access once, then it's cached locally.

## 4. Using it

1. **Policy Library** — upload your internal policies, ISO clauses, SOPs, and regulatory documents (PDF/DOCX/TXT/MD). These get chunked and embedded into the vector store.
2. **Documents** — upload the company process/procedure/record you want checked, then click **Analyze**. Optionally add a focus area (e.g. "supplier qualification records").
3. The agent retrieves the most relevant policy excerpts for that document (RAG), reasons over the comparison with Claude, and writes a structured **Risk Report**: compliance score, risk level, itemized gaps (with severity + recommendation), and strengths.
4. **Risk Reports** — every run is saved and browsable as an audit trail.
5. **Ask the Agent** — free-form Q&A against the policy corpus (and optionally a specific document) for quick lookups outside a full report.

## 5. API reference

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | Backend + LLM configuration status |
| POST | `/api/upload/policy` | Upload a policy/ISO/SOP file (multipart `file`) |
| POST | `/api/upload/document` | Upload a document to be checked (multipart `file`) |
| GET | `/api/files/{kind}` | List uploaded files (`kind` = `policy` or `document`) |
| DELETE | `/api/files/{kind}/{file_id}` | Remove a file and its indexed chunks |
| POST | `/api/analyze` | Run the full pipeline on a document → returns a `RiskReport` |
| GET | `/api/reports` | List all past risk reports |
| GET | `/api/reports/{report_id}` | Fetch one report |
| POST | `/api/ask` | Ad-hoc Q&A over the policy corpus / a document |

Interactive Swagger docs are auto-generated at **http://localhost:8000/docs**.

## 6. Notes on the tech choices

- **Vector DB:** ChromaDB, persisted to disk under `backend/data/vectorstore` — no external service to run.
- **Embeddings:** local `sentence-transformers` model, so ingestion doesn't cost API calls.
- **LLM reasoning:** Claude (`claude-sonnet-4-5` by default, configurable via `CLAUDE_MODEL` env var) does the policy-comparison and gap analysis, returning structured JSON that the backend validates and stores.
- **No Streamlit:** the frontend is a standard static HTML/CSS/JS single-page app served by FastAPI's `StaticFiles`, calling the JSON API with `fetch`. You can host it separately (e.g. Nginx, S3) and just point `API_BASE` in `app.js` at your backend URL if you ever split them apart.
