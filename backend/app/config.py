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


# Comma-separated emails allowed to access the admin dashboard.
ADMIN_EMAILS = {
    e.strip().lower()
    for e in os.getenv("ADMIN_EMAILS", "").split(",")
    if e.strip()
}

# Comma-separated Algorand wallet addresses allowed to sign in as admin via Pera.
ADMIN_WALLETS = {
    a.strip()
    for a in os.getenv("ADMIN_WALLETS", "").split(",")
    if a.strip()
}

APP_NAME = os.getenv("APP_NAME", "Inquvia")
TAGLINE = os.getenv("TAGLINE", "Investigate before you decide.")
SUBHEADLINE = os.getenv(
    "SUBHEADLINE",
    "Something looks suspicious, confusing, or too good to be true? Give it to Inquvia and get an evidence-backed assessment instead of a guess."
)
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
# when requests arrive via localhost. MUST be set to the actual public HTTPS
# deployment URL in production (e.g. https://inquvia.ai). No localhost fallback.
X402_PUBLIC_BASE_URL = os.getenv("X402_PUBLIC_BASE_URL", "").strip().rstrip("/")
if not X402_PUBLIC_BASE_URL:
    # Fallback to PUBLIC_APP_URL for local dev only; production MUST set this explicitly.
    X402_PUBLIC_BASE_URL = PUBLIC_APP_URL.rstrip("/") if PUBLIC_APP_URL else ""
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
MAX_UPLOAD_SIZE_MB = int(os.getenv("MAX_UPLOAD_SIZE_MB", "10"))
MAX_UPLOAD_SIZE = MAX_UPLOAD_SIZE_MB * 1024 * 1024

# ── Video evidence pipeline bounds (see libraries/video_processor.py) ──
# ffmpeg/ffprobe discovery: FFPROBE_PATH/FFMPEG_PATH override PATH lookup; on
# deployment the binaries must be installed (README/backend apt.txt).
VIDEO_MAX_FRAMES = int(os.getenv("VIDEO_MAX_FRAMES", "16"))
VIDEO_FFPROBE_TIMEOUT = float(os.getenv("VIDEO_FFPROBE_TIMEOUT", "30"))
VIDEO_FFMPEG_TIMEOUT = float(os.getenv("VIDEO_FFMPEG_TIMEOUT", "120"))
# Videos longer than this are degraded (metadata only, no frames/audio) so a
# single large upload can never pin CPU decoding for minutes on end.
VIDEO_MAX_DURATION_SECONDS = float(os.getenv("VIDEO_MAX_DURATION_SECONDS", "14400"))
# Transcription never feeds more than this many seconds of audio to the model.
AUDIO_TRANSCRIPT_WINDOW_SECONDS = int(os.getenv("AUDIO_TRANSCRIPT_WINDOW_SECONDS", "240"))
# Extracted frames are downscaled to this width before any AI call.
VIDEO_FRAME_MAX_WIDTH = int(os.getenv("VIDEO_FRAME_MAX_WIDTH", "640"))

ALLOWED_MIME = [
    "image/jpeg", "image/png", "image/webp", "image/gif", "image/bmp", "image/tiff", "image/heic", "image/heif",
    "video/mp4", "video/quicktime", "video/webm", "video/x-matroska", "video/x-msvideo", "video/mpeg", "video/x-m4v", "video/x-ms-wmv",
    "audio/mpeg", "audio/wav", "audio/mp3", "audio/ogg", "audio/x-m4a", "audio/mp4", "audio/aac", "audio/flac", "audio/opus", "audio/webm",
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/msword", "text/plain", "text/markdown", "text/x-markdown", "application/rtf",
    "application/vnd.oasis.opendocument.text",
    "text/csv", "text/tab-separated-values", "application/json", "application/x-jsonlines",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "application/vnd.ms-excel",
    "application/x-parquet", "application/parquet", "text/html", "application/xhtml+xml",
]

MIME_EXTENSIONS = {
    "image/jpeg": [".jpg", ".jpeg"], "image/png": [".png"], "image/webp": [".webp"], "image/gif": [".gif"],
    "image/bmp": [".bmp"], "image/tiff": [".tif", ".tiff"], "image/heic": [".heic"], "image/heif": [".heif"],
    "video/mp4": [".mp4"], "video/quicktime": [".mov"], "video/webm": [".webm"], "video/x-matroska": [".mkv"], "video/x-msvideo": [".avi"],
    "video/mpeg": [".mpeg", ".mpg"], "video/x-m4v": [".m4v"], "video/x-ms-wmv": [".wmv"],
    "audio/mpeg": [".mp3"], "audio/mp3": [".mp3"], "audio/wav": [".wav"], "audio/ogg": [".ogg"],
    "audio/x-m4a": [".m4a"], "audio/mp4": [".m4a"], "audio/aac": [".aac"], "audio/flac": [".flac"], "audio/opus": [".opus"], "audio/webm": [".webm"],
    "application/pdf": [".pdf"],
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": [".docx"],
    "application/msword": [".doc"], "text/plain": [".txt"], "text/markdown": [".md"], "text/x-markdown": [".md"],
    "application/rtf": [".rtf"], "application/vnd.oasis.opendocument.text": [".odt"],
    "text/csv": [".csv"], "text/tab-separated-values": [".tsv"], "application/json": [".json"],
    "application/x-jsonlines": [".jsonl"],
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": [".xlsx"],
    "application/vnd.ms-excel": [".xls"], "application/x-parquet": [".parquet"], "application/parquet": [".parquet"],
    "text/html": [".html", ".htm"], "application/xhtml+xml": [".xhtml"],
}


def mime_input_type(mime: str, capability_id: str | None = None) -> str:
    """Canonical MIME -> input type mapping used by paid input validation."""
    mime = (mime or "").lower().split(";", 1)[0].strip()
    if mime.startswith("image/"):
        return "image"
    if mime.startswith("video/") or mime in ("video/quicktime", "video/x-ms-wmv"):
        return "video"
    if mime.startswith("audio/"):
        return "audio"
    if mime in ("text/html", "application/xhtml+xml"):
        return "url" if capability_id in ("claim-investigation", "source-investigation") else "document"
    if mime in {
        "text/csv", "text/tab-separated-values", "application/json", "application/x-jsonlines",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "application/vnd.ms-excel",
        "application/x-parquet", "application/parquet",
    }:
        return "data"
    return "document"


ATOMIC_INPUT_TYPES = {
    "claim-investigation": {"text", "url", "document", "image", "video", "audio", "data"},
    "image-investigation": {"image", "url"},
    "image-batch-investigation": {"image", "url"},
    "video-investigation": {"video", "url"},
    "document-investigation": {"document", "text", "url"},
    "source-investigation": {"url"},
    "data-investigation": {"data", "url"},
    "audio-investigation": {"audio", "url"},
}


def capability_accepted_mimes(capability_id: str) -> list[str]:
    """MIME types a capability validates against for uploaded files."""
    if capability_id == "source-investigation":
        return []
    allowed = ATOMIC_INPUT_TYPES.get(capability_id, set())
    return [m for m in ALLOWED_MIME if mime_input_type(m, capability_id) in allowed]


def capability_accepted_extensions(capability_id: str) -> list[str]:
    seen: list[str] = []
    for mime in capability_accepted_mimes(capability_id):
        for ext in MIME_EXTENSIONS.get(mime, []):
            if ext not in seen:
                seen.append(ext)
    return seen

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or ""
GROQ_API_KEY = os.getenv("GROQ_API_KEY") or ""
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY") or ""
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY") or ""
EXPLABS_API_KEY = os.getenv("EXPLABS_API_KEY") or ""
# Reverse-image / near-duplicate search (optional). When unset the
# image_reverse_search evidence layer reports "not provisioned" honestly
# instead of fabricating hits.
SERPAPI_API_KEY = os.getenv("SERPAPI_API_KEY") or ""
# Maximum images per image-investigation (two-image comparison).
MAX_IMAGE_INPUTS = int(os.getenv("MAX_IMAGE_INPUTS", "2"))
MAX_BATCH_IMAGE_INPUTS = int(os.getenv("MAX_BATCH_IMAGE_INPUTS", "200"))

# Model IDs - override via env if needed; defaults are free-tier models
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free")
EXPLABS_MODEL = os.getenv("EXPLABS_MODEL", "deepseek-v4.1-flash")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

# Per-task model chains across the free models we run. Each task picks the
# best fit as primary, then falls back through cheaper/older free models.
# Chains stay within the Gemini API here; if the whole chain fails,
# call_ai_with_parts falls through to the other providers (Explabs,
# OpenRouter, Groq), so those act as the last-resort nets.
# - image/video/document/source/authenticity/audio report: multimodal,
#   fill-light tasks → keep flash-class models first.
# - claim/assess reasoning: heavier reasoning → pro models in the fallbacks.
# - data/structured/compute plans: structured output needs a small fast
#   model (lite class) that obeys JSON schemas reliably.
# - transcribe: audio-to-text models handle raw audio, flash models are
#   text-only fallbacks for transcript-of-transcript requests.
# Live / TTS / robotics / image-generation free models can't do one-shot
# JSON analysis over evidence, so they are intentionally not routed here.
# Per-task Gemini chain, tried in order (ai.call_ai_with_parts falls through on
# failure). Every chain leads with a model verified reachable on the current
# key: the pro/preview names below return 429/503 and, when they lead, the whole
# chain can dead-end into a null result. ponytail: pro models stay as later
# fallbacks; delete them if they stay unavailable.
MODEL_TASKS: dict[str, list[str]] = {
    "image": ["gemini-3.5-flash-lite", "gemini-3.1-pro-preview", "gemini-3.7-flash", "gemma-4-26b-a4b-it"],
    "video": ["gemini-3.5-flash-lite", "gemini-3.1-pro-preview", "gemini-3.7-flash", "gemma-4-26b-a4b-it"],
    "audio": ["gemini-3.5-flash-lite", "gemini-3.1-pro-preview", "gemma-4-26b-a4b-it"],
    "document": ["gemini-3.5-flash-lite", "gemini-3.1-pro-preview", "gemini-3.7-flash", "gemma-4-26b-a4b-it"],
    "web source": ["gemini-3.5-flash-lite", "gemini-3.1-pro-preview", "gemma-4-26b-a4b-it"],
    "source": ["gemini-3.5-flash-lite", "gemini-3.1-pro-preview", "gemma-4-26b-a4b-it"],
    "authenticity": ["gemini-3.5-flash-lite", "gemini-3.1-pro-preview", "gemini-3.7-flash"],
    "claim": ["gemini-3.5-flash-lite", "gemini-3.1-pro-preview", "gemini-3.7-flash"],
    "verify": ["gemini-3.5-flash-lite", "gemini-3.1-pro-preview", "gemini-3.7-flash"],
    "contradictions": ["gemini-3.5-flash-lite", "gemini-3.1-pro-preview", "gemini-3.7-flash"],
    "gaps": ["gemini-3.5-flash-lite", "gemini-3.1-pro-preview"],
    "plan": ["gemini-3.5-flash-lite", "gemini-3.1-pro-preview"],
    "structured": ["gemini-3.5-flash-lite", "gemini-flash-lite-latest"],
    "data": ["gemini-3.5-flash-lite", "gemini-flash-lite-latest"],
    "transcribe": ["gemini-3.5-transcribe", "gemini-3.5-transcribe-live", "gemini-3.5-flash-lite"],
}

def model_chain(task: str = "") -> list[str]:
    """Gemini models to try for a task (primary first). Unknown tasks use the default."""
    chain = MODEL_TASKS.get(task or "")
    return list(chain) if chain else [GEMINI_MODEL]

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
# Video can be priced separately; falls back to the shared price when unset.
VIDEO_INVESTIGATION_PRICE_USDC = _env_num("VIDEO_INVESTIGATION_PRICE_USDC") or INVESTIGATION_PRICE_USDC

PAID_CAPABILITIES = [
    {"id": "claim-investigation", "title": "Claim Investigation",
    "endpoint": "/api/x402/claim-investigation", "priceUsdc": INVESTIGATION_PRICE_USDC,
     "description": "Check whether a claim is supported by available evidence.",
     "inputTypes": ["text", "url", "document", "image", "video", "audio", "data"]},
{"id": "image-investigation", "title": "Image Investigation",
        "endpoint": "/api/x402/image-investigation", "priceUsdc": INVESTIGATION_PRICE_USDC,
        "description": "Investigate an image for context, provenance, and evidence.",
        "inputTypes": ["image", "url"]},
    {"id": "image-batch-investigation", "title": "Batch Image Investigation",
        "endpoint": "/api/x402/image-batch-investigation", "priceUsdc": INVESTIGATION_PRICE_USDC,
        "description": "Investigate many images for duplicates, clusters, and common sources.",
        "inputTypes": ["image", "url"]},
    {"id": "video-investigation", "title": "Video Investigation",
        "endpoint": "/api/x402/video-investigation", "priceUsdc": VIDEO_INVESTIGATION_PRICE_USDC,
        "description": "Investigate what a video shows and whether its context holds up.",
        "inputTypes": ["video", "url"]},
    {"id": "document-investigation", "title": "Document Investigation",
        "endpoint": "/api/x402/document-investigation", "priceUsdc": INVESTIGATION_PRICE_USDC,
        "description": "Examine a document for findings, inconsistencies, and evidence.",
        "inputTypes": ["document", "url"]},
    {"id": "source-investigation", "title": "Source Investigation",
        "endpoint": "/api/x402/source-investigation", "priceUsdc": INVESTIGATION_PRICE_USDC,
        "description": "Investigate a website or source before you trust it.",
        "inputTypes": ["url"]},
    {"id": "data-investigation", "title": "Data Investigation",
        "endpoint": "/api/x402/data-investigation", "priceUsdc": INVESTIGATION_PRICE_USDC,
        "description": "Investigate structured data for anomalies and supporting signals.",
        "inputTypes": ["data", "url"]},
    {"id": "audio-investigation", "title": "Audio Investigation",
        "endpoint": "/api/x402/audio-investigation", "priceUsdc": INVESTIGATION_PRICE_USDC,
        "description": "Investigate an audio recording for transcript, context, and evidence.",
        "inputTypes": ["audio", "url"]},
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
