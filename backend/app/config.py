"""Central backend configuration (mirrors src/lib/config.ts)."""
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]  # D:\Inquvia
load_dotenv(ROOT / ".env")


def _env_num(name: str) -> float:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return 0.0
    try:
        return float(raw)
    except ValueError:
        return 0.0


APP_NAME = os.getenv("APP_NAME", "Inquvia")
PUBLIC_APP_URL = (
    os.getenv("PUBLIC_APP_URL", "").strip()
    or os.getenv("NEXT_PUBLIC_SITE_URL", "").strip()
).rstrip("/")

MONGODB_URI = os.getenv("MONGODB_URI", "")
MONGODB_DB_NAME = os.getenv("MONGODB_DB_NAME", "Inquvia")

ALGORAND_NETWORK = os.getenv("NEXT_PUBLIC_ALGORAND_NETWORK", None) or os.getenv("ALGORAND_NETWORK", "mainnet")
ALGORAND_USDC_ASA = os.getenv("ALGORAND_USDC_ASA", "").strip()
X402_FACILITATOR_URL = os.getenv("X402_FACILITATOR_URL", "https://facilitator.goplausible.xyz")
# Required for the Global x402 Challenge Bazaar listing when no deployment
# override is supplied. Production can still set the same value explicitly.
X402_CHALLENGE_TAG = os.getenv("X402_CHALLENGE_TAG", "x402-global-challenge")
# Canonical public origin served in every 402 PAYMENT-REQUIRED so settles
# attribute to the deployed resource host (bazaar/challenge dashboard), even
# when requests arrive via localhost. Synced with PUBLIC_APP_URL by default.
X402_PUBLIC_BASE_URL = (
    os.getenv("X402_PUBLIC_BASE_URL", "").strip()
    or PUBLIC_APP_URL
).rstrip("/")
INQUVIA_PAYTO_ADDRESS = os.getenv("INQUVIA_PAYTO_ADDRESS", "").strip()

# x402 payment gating is FAIL-CLOSED: when the middleware is unavailable the
# atomic endpoints return 402, never run free. The only exception is an
# explicit INQUVIA_X402_OFFLINE=1 (local dev) flag; even then no payment is
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

STORAGE_PATH = Path(os.getenv("STORAGE_PATH", str(ROOT / "backend" / "data" / "uploads")))
MAX_UPLOAD_SIZE = 10 * 1024 * 1024  # 10MB

ALLOWED_MIME = [
    "image/jpeg", "image/png", "image/webp", "image/gif",
    "video/mp4", "video/webm",
    "audio/mpeg", "audio/wav", "audio/mp3", "audio/ogg",
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

# All capability endpoints use one shared price in whole USDC dollars.
INVESTIGATION_PRICE_USDC = _env_num("INVESTIGATION_PRICE_USDC")

PAID_CAPABILITIES = [
    {"id": "claim-investigation", "title": "Claim Investigation",
    "endpoint": "/api/x402/claim-investigation", "priceUsdc": INVESTIGATION_PRICE_USDC,
     "description": "Check whether a claim is supported by available evidence.",
     "inputTypes": ["text"]},
    {"id": "image-investigation", "title": "Image Investigation",
        "endpoint": "/api/x402/image-investigation", "priceUsdc": INVESTIGATION_PRICE_USDC,
     "description": "Investigate an image for context, provenance, and evidence.",
     "inputTypes": ["image"]},
    {"id": "video-investigation", "title": "Video Investigation",
        "endpoint": "/api/x402/video-investigation", "priceUsdc": INVESTIGATION_PRICE_USDC,
     "description": "Investigate what a video shows and whether its context holds up.",
     "inputTypes": ["video"]},
    {"id": "document-investigation", "title": "Document Investigation",
        "endpoint": "/api/x402/document-investigation", "priceUsdc": INVESTIGATION_PRICE_USDC,
     "description": "Examine a document for findings, inconsistencies, and evidence.",
     "inputTypes": ["document"]},
    {"id": "source-investigation", "title": "Source Investigation",
        "endpoint": "/api/x402/source-investigation", "priceUsdc": INVESTIGATION_PRICE_USDC,
     "description": "Investigate a website or source before you trust it.",
     "inputTypes": ["url"]},
    {"id": "data-investigation", "title": "Data Investigation",
        "endpoint": "/api/x402/data-investigation", "priceUsdc": INVESTIGATION_PRICE_USDC,
     "description": "Investigate structured data for anomalies and supporting signals.",
     "inputTypes": ["data"]},
    {"id": "audio-investigation", "title": "Audio Investigation",
        "endpoint": "/api/x402/audio-investigation", "priceUsdc": INVESTIGATION_PRICE_USDC,
     "description": "Investigate an audio recording for transcript, context, and evidence.",
     "inputTypes": ["audio"]},
]

EVIDENCE_CAPABILITIES = [
    {"id": "evidence-image", "title": "Image Evidence", "endpoint": "/api/evidence/image", "description": "Extract and analyze evidence from an image."},
    {"id": "evidence-video", "title": "Video Evidence", "endpoint": "/api/evidence/video", "description": "Extract and analyze evidence from a video."},
    {"id": "evidence-url", "title": "URL Evidence", "endpoint": "/api/evidence/url", "description": "Inspect and analyze a public source URL."},
    {"id": "evidence-document", "title": "Document Evidence", "endpoint": "/api/evidence/document", "description": "Extract and analyze evidence from a document."},
    {"id": "evidence-structured", "title": "Structured Evidence", "endpoint": "/api/evidence/structured", "description": "Analyze a JSON or CSV data source."},
    {"id": "evidence-audio", "title": "Audio Evidence", "endpoint": "/api/evidence/audio", "description": "Extract and analyze evidence from audio."},
    {"id": "evidence-assess", "title": "Evidence Assessment", "endpoint": "/api/evidence/assess", "description": "Assess a claim against supplied evidence."},
    {"id": "evidence-contradictions", "title": "Contradictions", "endpoint": "/api/evidence/contradictions", "description": "Find contradictions in supplied evidence."},
    {"id": "evidence-duplicates", "title": "Duplicate Analysis", "endpoint": "/api/evidence/duplicates", "description": "Find duplicate and dependent evidence."},
    {"id": "evidence-timeline", "title": "Timeline", "endpoint": "/api/evidence/timeline", "description": "Reconstruct a timeline from supplied evidence."},
    {"id": "evidence-authenticity", "title": "Authenticity", "endpoint": "/api/evidence/authenticity", "description": "Report forensic consistency signals for media."},
    {"id": "evidence-gaps", "title": "Evidence Gaps", "endpoint": "/api/evidence/gaps", "description": "Identify missing evidence and unresolved questions."},
]

DEFAULT_PAYMENT_PREFS = {
    "maxPerEvidenceCheck": 0.01,
    "maxPerInvestigation": INVESTIGATION_PRICE_USDC,
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
