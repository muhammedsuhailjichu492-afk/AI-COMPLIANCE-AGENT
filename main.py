

from __future__ import annotations
from pathlib import Path
from datetime import datetime, timezone
import shutil
import uuid
import json

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

import config
from document_processor import process_file
from rag_engine import rag_engine
import compliance_agent
from models import FileInfo, RiskReport, AnalyzeRequest, AskRequest

app = FastAPI(title="AI Quality & Compliance Intelligence Agent", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # loosen for local dev; restrict in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

REGISTRY_PATH = config.DATA_DIR / "registry.json"
ALLOWED_EXT = {".pdf", ".docx", ".txt", ".md"}
REGISTRY_KEY = {"policy": "policies", "document": "documents"}


# ---------------------------------------------------------------------------
# Tiny JSON-file registry of uploaded files (id -> metadata)
# ---------------------------------------------------------------------------
def _load_registry() -> dict:
    if REGISTRY_PATH.exists():
        return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    return {"policies": {}, "documents": {}}


def _save_registry(reg: dict) -> None:
    REGISTRY_PATH.write_text(json.dumps(reg, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------
@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "llm_configured": bool(config.ANTHROPIC_API_KEY),
        "time": datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------
def _handle_upload(file: UploadFile, kind: str) -> FileInfo:
    suffix = Path(file.filename).suffix.lower()
    if suffix not in ALLOWED_EXT:
        raise HTTPException(400, f"Unsupported file type '{suffix}'. Allowed: {sorted(ALLOWED_EXT)}")

    file_id = str(uuid.uuid4())
    target_dir = config.POLICIES_DIR if kind == "policy" else config.DOCUMENTS_DIR
    dest_path = target_dir / f"{file_id}{suffix}"

    with dest_path.open("wb") as f:
        shutil.copyfileobj(file.file, f)

    try:
        chunks = process_file(dest_path)
        if kind == "policy":
            n = rag_engine.add_policy_chunks(file_id, file.filename, chunks)
        else:
            n = rag_engine.add_document_chunks(file_id, file.filename, chunks)
    except Exception as exc:
        dest_path.unlink(missing_ok=True)
        raise HTTPException(500, f"Failed to process file: {exc}") from exc

    info = FileInfo(
        id=file_id,
        filename=file.filename,
        kind=kind,
        chunks=n,
        uploaded_at=datetime.now(timezone.utc).isoformat(),
    )

    reg = _load_registry()
    reg[REGISTRY_KEY[kind]][file_id] = info.model_dump()
    _save_registry(reg)

    return info


@app.post("/api/upload/policy", response_model=FileInfo)
async def upload_policy(file: UploadFile = File(...)):
    """Upload a policy / ISO / SOP reference document into the RAG corpus."""
    return _handle_upload(file, "policy")


@app.post("/api/upload/document", response_model=FileInfo)
async def upload_document(file: UploadFile = File(...)):
    """Upload a company process/record document to be checked for compliance."""
    return _handle_upload(file, "document")


# ---------------------------------------------------------------------------
# Listing / deletion
# ---------------------------------------------------------------------------
@app.get("/api/files/{kind}")
def list_files(kind: str):
    if kind not in ("policy", "document"):
        raise HTTPException(400, "kind must be 'policy' or 'document'")
    reg = _load_registry()
    return list(reg[REGISTRY_KEY[kind]].values())


@app.delete("/api/files/{kind}/{file_id}")
def delete_file(kind: str, file_id: str):
    if kind not in ("policy", "document"):
        raise HTTPException(400, "kind must be 'policy' or 'document'")
    reg = _load_registry()
    entry = reg[REGISTRY_KEY[kind]].pop(file_id, None)
    if not entry:
        raise HTTPException(404, "File not found")
    _save_registry(reg)
    rag_engine.delete_file(kind, file_id)

    target_dir = config.POLICIES_DIR if kind == "policy" else config.DOCUMENTS_DIR
    for p in target_dir.glob(f"{file_id}.*"):
        p.unlink(missing_ok=True)

    return {"deleted": True}


# ---------------------------------------------------------------------------
# Analysis / Risk Reports
# ---------------------------------------------------------------------------
@app.post("/api/analyze", response_model=RiskReport)
def analyze(req: AnalyzeRequest):
    reg = _load_registry()
    doc_entry = reg["documents"].get(req.document_id)
    if not doc_entry:
        raise HTTPException(404, "Document not found. Upload it first via /api/upload/document.")

    try:
        report = compliance_agent.analyze_document(
            document_id=req.document_id,
            document_name=doc_entry["filename"],
            focus_query=req.focus_query,
        )
    except RuntimeError as exc:
        raise HTTPException(400, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc

    return report


@app.get("/api/reports", response_model=list[RiskReport])
def get_reports():
    return compliance_agent.list_reports()


@app.get("/api/reports/{report_id}", response_model=RiskReport)
def get_report(report_id: str):
    report = compliance_agent.get_report(report_id)
    if not report:
        raise HTTPException(404, "Report not found")
    return report


# ---------------------------------------------------------------------------
# Ad-hoc Q&A
# ---------------------------------------------------------------------------
@app.post("/api/ask")
def ask(req: AskRequest):
    try:
        answer = compliance_agent.ask_question(req.question, req.document_id)
    except RuntimeError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"answer": answer}


# ---------------------------------------------------------------------------
# Serve the plain HTML/CSS/JS frontend (no Streamlit) from the same server
# ---------------------------------------------------------------------------
FRONTEND_DIR = (Path(__file__).resolve().parent.parent / "frontend")
if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
