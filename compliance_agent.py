

from __future__ import annotations
from typing import List, Dict, Any
from datetime import datetime, timezone
import json
import re
import uuid

from anthropic import APIError, Anthropic

from config import ANTHROPIC_API_KEY, CLAUDE_MODEL, REPORTS_DIR
from rag_engine import rag_engine
from models import RiskReport, ComplianceGap

_client = Anthropic(api_key=ANTHROPIC_API_KEY) if ANTHROPIC_API_KEY else None

SYSTEM_PROMPT = """You are an AI Quality & Compliance Intelligence Agent.
You continuously check company processes and documents against internal
policies, ISO standards, SOPs, and regulatory/compliance requirements.

Given:
1. Excerpts from a COMPANY DOCUMENT (a process, procedure, or record).
2. Relevant excerpts retrieved from the organization's POLICY / ISO / SOP
   corpus via retrieval-augmented search.

Your job:
- Compare the company document against the policy excerpts.
- Identify concrete compliance gaps, risks, or deviations.
- Note genuine strengths (things clearly done right / well documented).
- Score overall compliance 0-100 and assign a risk level.
- Be specific and cite which policy snippet each gap relates to.
- Do not invent policy content that was not provided to you — if the
  retrieved policy excerpts don't cover an area, say so as a gap in policy
  coverage rather than fabricating a rule.

Respond with ONLY valid JSON (no markdown fences, no commentary) matching
exactly this schema:
{
  "overall_compliance_score": <int 0-100>,
  "risk_level": "<low|medium|high|critical>",
  "summary": "<2-4 sentence executive summary>",
  "gaps": [
    {
      "issue": "<what is missing or non-compliant>",
      "related_policy_snippet": "<short paraphrase of the relevant policy requirement>",
      "severity": "<high|medium|low>",
      "recommendation": "<concrete corrective action>"
    }
  ],
  "strengths": ["<short strength statement>", "..."]
}
"""


def _build_document_context(file_id: str, max_chunks: int = 40) -> List[Dict[str, Any]]:
    return rag_engine.get_all_document_chunks(file_id)[:max_chunks]


def _retrieve_policy_context(document_chunks: List[Dict[str, Any]], focus_query: str | None) -> List[Dict[str, Any]]:
    """Run RAG: for the document's own content (and any extra focus query),
    retrieve the most relevant policy chunks. This is the 'RAG' + 'Policy
    Analysis' step — we let the document's own text drive retrieval so the
    policies pulled back are the ones actually relevant to what's in it.
    """
    seen_ids = set()
    retrieved: List[Dict[str, Any]] = []

    queries = []
    if focus_query:
        queries.append(focus_query)
    # Sample a handful of representative document chunks as retrieval queries
    sample = document_chunks[:: max(1, len(document_chunks) // 6)][:6] if document_chunks else []
    queries.extend([c["text"] for c in sample])

    for q in queries:
        for hit in rag_engine.query_policies(q, top_k=5):
            key = (hit["metadata"].get("filename"), hit["metadata"].get("chunk_index"))
            if key not in seen_ids:
                seen_ids.add(key)
                retrieved.append(hit)

    return retrieved[:25]


def _call_claude(document_text: str, policy_text: str, focus_query: str | None) -> Dict[str, Any]:
    user_prompt = f"""COMPANY DOCUMENT EXCERPTS:
---
{document_text}
---

RETRIEVED POLICY / ISO / SOP EXCERPTS:
---
{policy_text if policy_text.strip() else "(No matching policy excerpts were found in the policy corpus.)"}
---
"""
    if focus_query:
        user_prompt += f"\nADDITIONAL FOCUS REQUESTED BY THE USER: {focus_query}\n"

    response = _client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=2500,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
    )

    raw_text = "".join(block.text for block in response.content if block.type == "text")
    return _parse_json(raw_text)


# ---------------------------------------------------------------------------
# No-API-key fallback: local embedding-similarity heuristics.
# Runs entirely offline (uses the same embeddings already computed by the
# RAG engine) so the app is fully usable without an ANTHROPIC_API_KEY.
# Quality is lower than the LLM path, but it produces real, useful reports.
# ---------------------------------------------------------------------------
STRONG_MATCH_DISTANCE = 0.35
WEAK_MATCH_DISTANCE = 0.60


def _heuristic_analysis(policy_hits: List[Dict[str, Any]], focus_query: str | None) -> Dict[str, Any]:
    if not policy_hits:
        return {
            "overall_compliance_score": 50,
            "risk_level": "medium",
            "summary": (
                "No matching policy content was found in the policy library for this document, "
                "so compliance coverage could not be verified. Upload relevant policies, ISO "
                "clauses or SOPs to improve this result. (Generated with local similarity "
                "heuristics because no ANTHROPIC_API_KEY is configured.)"
            ),
            "gaps": [],
            "strengths": [],
        }

    strengths: List[str] = []
    gaps: List[Dict[str, str]] = []

    for hit in policy_hits:
        distance = hit.get("distance", 1.0)
        snippet = hit["text"][:220].strip().replace("\n", " ")
        source = hit["metadata"].get("filename", "policy")

        if distance <= STRONG_MATCH_DISTANCE:
            strengths.append(f"Content closely matching this policy requirement was found (source: {source}).")
        elif distance <= WEAK_MATCH_DISTANCE:
            gaps.append({
                "issue": "The document appears to only weakly or indirectly address this policy requirement.",
                "related_policy_snippet": f"[{source}] {snippet}",
                "severity": "medium",
                "recommendation": "Review the document against this requirement and add explicit language or records that clearly address it.",
            })

    total = len(strengths) + len(gaps)
    score = round((len(strengths) / total) * 100) if total else 50
    if score >= 80:
        risk_level = "low"
    elif score >= 55:
        risk_level = "medium"
    elif score >= 30:
        risk_level = "high"
    else:
        risk_level = "critical"

    summary = (
        f"Local similarity screening compared this document against {total} matched policy "
        f"excerpts: {len(strengths)} appear well covered and {len(gaps)} appear weakly or "
        f"indirectly addressed. This report was generated with local embedding-similarity "
        f"heuristics, not an LLM, because no ANTHROPIC_API_KEY is configured. Set that key to "
        f"enable full LLM compliance reasoning with more precise gap analysis and recommendations."
    )
    if focus_query:
        summary += f" Focus area requested: {focus_query}."

    return {
        "overall_compliance_score": score,
        "risk_level": risk_level,
        "summary": summary,
        "gaps": gaps,
        "strengths": strengths,
    }


def _parse_json(raw_text: str) -> Dict[str, Any]:
    cleaned = re.sub(r"^```(json)?|```$", "", raw_text.strip(), flags=re.MULTILINE).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if match:
            return json.loads(match.group(0))
        raise


def analyze_document(document_id: str, document_name: str, focus_query: str | None = None) -> RiskReport:
    """Full Policy Analysis -> Compliance Reasoning -> Risk Report pipeline.
    Uses Claude when ANTHROPIC_API_KEY is configured, otherwise falls back to
    local embedding-similarity heuristics so the app works with no API key.
    """

    document_chunks = _build_document_context(document_id)
    if not document_chunks:
        raise ValueError("Document not found or has no extracted content.")

    policy_hits = _retrieve_policy_context(document_chunks, focus_query)

    if _client is not None:
        document_text = "\n\n".join(c["text"] for c in document_chunks)
        policy_text = "\n\n".join(
            f"[Source: {h['metadata'].get('filename')}] {h['text']}" for h in policy_hits
        )
        result = _call_claude(document_text, policy_text, focus_query)
    else:
        result = _heuristic_analysis(policy_hits, focus_query)

    gaps = [ComplianceGap(**g) for g in result.get("gaps", [])]
    policies_referenced = sorted({h["metadata"].get("filename", "unknown") for h in policy_hits})

    report = RiskReport(
        id=str(uuid.uuid4()),
        document_id=document_id,
        document_name=document_name,
        generated_at=datetime.now(timezone.utc).isoformat(),
        overall_compliance_score=int(result.get("overall_compliance_score", 0)),
        risk_level=result.get("risk_level", "medium"),
        summary=result.get("summary", ""),
        gaps=gaps,
        strengths=result.get("strengths", []),
        policies_referenced=policies_referenced,
    )

    _persist_report(report)
    return report


def _persist_report(report: RiskReport) -> None:
    path = REPORTS_DIR / f"{report.id}.json"
    path.write_text(report.model_dump_json(indent=2), encoding="utf-8")


def list_reports() -> List[RiskReport]:
    reports = []
    for path in sorted(REPORTS_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        reports.append(RiskReport.model_validate_json(path.read_text(encoding="utf-8")))
    return reports


def get_report(report_id: str) -> RiskReport | None:
    path = REPORTS_DIR / f"{report_id}.json"
    if not path.exists():
        return None
    return RiskReport.model_validate_json(path.read_text(encoding="utf-8"))


def ask_question(question: str, document_id: str | None = None) -> str:
    """Ad-hoc Q&A over the policy corpus (and optionally a specific document),
    used by the chat box in the UI for quick lookups outside a full report.
    Uses Claude when configured, otherwise returns the raw retrieved
    excerpts directly (no LLM synthesis) so this still works with no key.
    """
    policy_hits = rag_engine.query_policies(question, top_k=6)

    doc_chunks: List[Dict[str, Any]] = []
    if document_id:
        doc_chunks = rag_engine.query_documents(question, file_id=document_id, top_k=6)

    if _client is None:
        return _raw_excerpt_answer(policy_hits, doc_chunks)

    policy_text = "\n\n".join(
        f"[Source: {h['metadata'].get('filename')}] {h['text']}" for h in policy_hits
    )
    doc_text = "\n\n".join(c["text"] for c in doc_chunks)

    prompt = f"""Answer the user's question using only the excerpts below. If the
excerpts don't contain the answer, say so explicitly rather than guessing.

POLICY EXCERPTS:
{policy_text or "(none found)"}

DOCUMENT EXCERPTS:
{doc_text or "(none provided)"}

QUESTION: {question}
"""
    try:
        response = _client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=800,
            system="You are a precise compliance assistant. Cite which source each fact comes from.",
            messages=[{"role": "user", "content": prompt}],
        )
    except APIError:
        return _raw_excerpt_answer(
            policy_hits,
            doc_chunks,
            notice="Claude was unavailable, so these are the most relevant excerpts found by retrieval:",
        )
    return "".join(block.text for block in response.content if block.type == "text")


def _raw_excerpt_answer(
    policy_hits: List[Dict[str, Any]],
    doc_chunks: List[Dict[str, Any]],
    notice: str | None = None,
) -> str:
    lines = [notice or "No ANTHROPIC_API_KEY is configured, so here are the most relevant excerpts found by retrieval:", ""]
    unique_policy_hits = _unique_hits(policy_hits)
    unique_doc_chunks = _unique_hits(doc_chunks)
    if unique_policy_hits:
        lines.append("From the policy library:")
        for hit in unique_policy_hits:
            source = hit["metadata"].get("filename", "policy")
            snippet = _excerpt(hit["text"])
            lines.append(f"- [{source}] {snippet}")
    if unique_doc_chunks:
        lines.append("")
        lines.append("From the selected document:")
        for chunk in unique_doc_chunks:
            snippet = _excerpt(chunk["text"])
            lines.append(f"- {snippet}")
    if not unique_policy_hits and not unique_doc_chunks:
        lines.append("No relevant content was found for this question.")
    return "\n".join(lines)


def _unique_hits(hits: List[Dict[str, Any]], limit: int = 5) -> List[Dict[str, Any]]:
    """Remove repeated overlapping chunks while preserving retrieval order."""
    unique: List[Dict[str, Any]] = []
    seen_prefixes = set()
    for hit in hits:
        normalized = " ".join(hit["text"].split()).lower()
        prefix = normalized[:120]
        if prefix in seen_prefixes:
            continue
        seen_prefixes.add(prefix)
        unique.append(hit)
        if len(unique) == limit:
            break
    return unique


def _excerpt(text: str, max_length: int = 360) -> str:
    snippet = " ".join(text.split()).strip()
    if len(snippet) > max_length:
        snippet = snippet[:max_length].rsplit(" ", 1)[0].rstrip(".,;:") + "..."
    if snippet and snippet[0].islower():
        snippet = "... " + snippet.split(" ", 1)[1]
    return snippet
