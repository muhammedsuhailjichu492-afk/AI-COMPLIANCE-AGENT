

import os
from pathlib import Path

from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"

load_dotenv(BASE_DIR / ".env")

POLICIES_DIR = DATA_DIR / "policies"       # raw uploaded policy/ISO/SOP files
DOCUMENTS_DIR = DATA_DIR / "documents"     # raw uploaded process/company docs
VECTORSTORE_DIR = DATA_DIR / "vectorstore" # persisted Chroma DB
REPORTS_DIR = DATA_DIR / "reports"         # generated risk reports (JSON)

for d in (POLICIES_DIR, DOCUMENTS_DIR, VECTORSTORE_DIR, REPORTS_DIR):
    d.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# LLM / Embeddings
# ---------------------------------------------------------------------------
# The reasoning agent calls Anthropic's Claude models. Set this in your
# environment before starting the server:
#   export ANTHROPIC_API_KEY="sk-ant-..."
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-5")

# Local, free sentence-transformer model used for embeddings (no API key
# needed). Swap for a larger model if you want higher retrieval quality.
EMBEDDING_MODEL_NAME = os.environ.get("EMBEDDING_MODEL_NAME", "all-MiniLM-L6-v2")

# ---------------------------------------------------------------------------
# Chunking / retrieval
# ---------------------------------------------------------------------------
CHUNK_SIZE = 800          # characters per chunk
CHUNK_OVERLAP = 150       # characters of overlap between consecutive chunks
TOP_K_POLICY_CHUNKS = 6   # how many policy chunks to retrieve per query

# ---------------------------------------------------------------------------
# Chroma collection names
# ---------------------------------------------------------------------------
POLICY_COLLECTION = "policies"
DOCUMENT_COLLECTION = "documents"
