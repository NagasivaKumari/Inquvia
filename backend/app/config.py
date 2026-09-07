"""Central backend configuration (mirrors src/lib/config.ts)."""
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]  # D:\Inquvia
load_dotenv(ROOT / ".env")


def _num(name: str, fallback: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return fallback
    try:
        return float(raw)
    except ValueError:
        return fallback


APP_NAME = os.getenv("APP_NAME", "Inquvia")
PUBLIC_APP_URL = os.getenv("PUBLIC_APP_URL", "").rstrip("/")

MONGODB_URI = os.getenv("MONGODB_URI", "")
MONGODB_DB_NAME = os.getenv("MONGODB_DB_NAME", "Inquvia")

ALGORAND_NETWORK = os.getenv("NEXT_PUBLIC_ALGORAND_NETWORK", None) or os.getenv("ALGORAND_NETWORK", "mainnet")
ALGORAND_USDC_ASA = os.getenv("ALGORAND_USDC_ASA", "31566704")
X402_FACILITATOR_URL = os.getenv("X402_FACILITATOR_URL", "https://facilitator.goplausible.xyz")
X402_CHALLENGE_TAG = os.getenv("X402_CHALLENGE_TAG", "inquvia")
INQUVIA_PAYTO_ADDRESS = os.getenv("INQUVIA_PAYTO_ADDRESS", "").strip()
SERVER_WALLET_MNEMONIC = os.getenv("SERVER_WALLET_MNEMONIC", "")

# x402 payment gating is FAIL-CLOSED: when the middleware is unavailable the
# atomic endpoints return 402, never run free. The only exception is an
# explicit INQUVIA_X402_OFFLINE=1 (local dev) flag; even then no payment is
# recorded. There is no server wallet: Inquvia never holds or spends funds and
# downstream evidence providers are paid directly by the user's wallet.
INQUVIA_X402_OFFLINE = os.getenv("INQUVIA_X402_OFFLINE", "") == "1"

# "Session" window for the per-session spending budget (sliding hours).
SESSION_BUDGET_WINDOW_HOURS = int(os.getenv("SESSION_BUDGET_WINDOW_HOURS", "24"))

# Algorand node (algod) for on-chain settlement verification.
ALGOD_TOKEN = os.getenv("ALGOD_TOKEN", "")
ALGOD_SERVER = os.getenv("ALGOD_SERVER", "").strip() or (
    "https://testnet-api.algonode.cloud" if ALGORAND_NETWORK == "testnet"
    else "https://mainnet-api.algonode.cloud"
)
ALGOD_PORT = int(os.getenv("ALGOD_PORT", "443"))

ALGORAND_NETWORK_CAIP2 = (
    "algorand:SGO1GKSzyE7IEPItTxCByw9x8FmnrCDexi9/cOUJOiI="
    if ALGORAND_NETWORK == "testnet"
    else "algorand:wGHE2Pwdvd7S12BL5FaOP20EGYesN73ktiC1qzkkit8="
)

# Evidence discovery configuration (never fabricates providers).
EXTERNAL_EVIDENCE_SERVICES_URL = os.getenv("EXTERNAL_EVIDENCE_SERVICES_URL", "")
EXTERNAL_EVIDENCE_SERVICES_JSON = os.getenv("EXTERNAL_EVIDENCE_SERVICES_JSON", "")
EVIDENCE_SERVICE_URL = (os.getenv("EVIDENCE_SERVICE_URL") or "").rstrip("/")

STORAGE_PATH = Path(os.getenv("STORAGE_PATH", str(ROOT / "backend" / "data" / "uploads")))
MAX_UPLOAD_SIZE = 10 * 1024 * 1024  # 10MB

ALLOWED_MIME = [
    "image/jpeg", "image/png", "image/webp", "image/gif",
    "video/mp4", "video/webm",
    "application/pdf", "text/plain", "text/csv", "application/json",
]

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or ""
GROQ_API_KEY = os.getenv("GROQ_API_KEY") or ""
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY") or ""
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY") or ""

ALGORAND_USDC_DECIMALS = 1_000_000  # 6 decimals

INVESTIGATION_STAGES = [
    {"id": "created", "label": "Investigating"},
    {"id": "planning", "label": "Planning investigation"},
    {"id": "discovering", "label": "Discovering evidence services"},
    {"id": "awaiting_payment", "label": "Payment required"},
    {"id": "payment_pending", "label": "Payment pending"},
    {"id": "evidence_requested", "label": "Acquiring evidence"},
    {"id": "evidence_received", "label": "Evidence received"},
    {"id": "analyzing", "label": "Analyzing evidence"},
    {"id": "cross_checking", "label": "Cross-checking evidence"},
    {"id": "assessment", "label": "Final assessment"},
]

INVESTIGATION_BLOCKED_STATES = [
    "payment_failed", "settlement_failed", "evidence_unavailable", "blocked", "failed",
]

# Capability prices in whole USDC dollars.
PAID_CAPABILITIES = [
    {"id": "claim-investigation", "title": "Claim Investigation",
     "endpoint": "/api/x402/claim-investigation", "priceUsdc": _num("CLAIM_INVESTIGATION_PRICE_USDC", 0.5),
     "description": "Check whether a claim is supported by available evidence.",
     "inputTypes": ["text"]},
    {"id": "image-investigation", "title": "Image Investigation",
     "endpoint": "/api/x402/image-investigation", "priceUsdc": _num("IMAGE_INVESTIGATION_PRICE_USDC", 0.5),
     "description": "Investigate an image for context, provenance, and evidence.",
     "inputTypes": ["image"]},
    {"id": "video-investigation", "title": "Video Investigation",
     "endpoint": "/api/x402/video-investigation", "priceUsdc": _num("VIDEO_INVESTIGATION_PRICE_USDC", 0.5),
     "description": "Investigate what a video shows and whether its context holds up.",
     "inputTypes": ["video"]},
    {"id": "document-investigation", "title": "Document Investigation",
     "endpoint": "/api/x402/document-investigation", "priceUsdc": _num("DOCUMENT_INVESTIGATION_PRICE_USDC", 0.5),
     "description": "Examine a document for findings, inconsistencies, and evidence.",
     "inputTypes": ["document"]},
    {"id": "source-investigation", "title": "Source Investigation",
     "endpoint": "/api/x402/source-investigation", "priceUsdc": _num("SOURCE_INVESTIGATION_PRICE_USDC", 0.5),
     "description": "Investigate a website or source before you trust it.",
     "inputTypes": ["url"]},
    {"id": "data-investigation", "title": "Data Investigation",
     "endpoint": "/api/x402/data-investigation", "priceUsdc": _num("DATA_INVESTIGATION_PRICE_USDC", 0.5),
     "description": "Investigate structured data for anomalies and supporting signals.",
     "inputTypes": ["data"]},
]

DEFAULT_PAYMENT_PREFS = {
    "maxPerEvidenceCheck": 0.01,
    "maxPerInvestigation": 0.50,
    "sessionBudget": 5.00,
    "totalBudget": 50.00,
}

SESSIONS_EXPIRE_AFTER_DAYS = 30
SESSION_COOKIE = "inquvia_session"
JWT_SECRET = os.getenv("JWT_SECRET")
if not JWT_SECRET:
    raise ValueError("JWT_SECRET environment variable must be set")


def get_paid_capability(capability_id: str) -> dict | None:
    for c in PAID_CAPABILITIES:
        if c["id"] == capability_id:
            return c
    return None