"""
Centralized registry for authoritative input contract schemas for all evidence endpoints.

This module acts as the single source of truth for endpoint definitions,
which are used by both backend validation and frontend display.
"""
from typing import Any, Dict, List, Optional, Literal
from pydantic import BaseModel

# ── Constants (centralized) ──
MAX_UPLOAD_SIZE_MB = 10

ALLOWED_IMAGE_MIME = [
    "image/jpeg", "image/png", "image/webp", "image/gif", "image/bmp", "image/tiff", "image/heic", "image/heif"
]
ALLOWED_VIDEO_MIME = [
    "video/mp4", "video/webm", "video/x-matroska", "video/x-msvideo", "video/mpeg", "video/x-m4v"
]
ALLOWED_AUDIO_MIME = [
    "audio/mpeg", "audio/wav", "audio/ogg", "audio/x-m4a", "audio/aac", "audio/flac", "audio/webm"
]
ALLOWED_DOCUMENT_MIME = [
    "application/pdf", 
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document", 
    "application/msword", 
    "text/plain", 
    "text/markdown", 
    "application/rtf", 
    "application/vnd.oasis.opendocument.text"
]
ALLOWED_STRUCTURED_MIME = [
    "application/json", 
    "application/x-jsonlines", 
    "text/csv", 
    "text/tab-separated-values", 
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", 
    "application/vnd.ms-excel", 
    "application/x-parquet"
]


# ── Schema Definitions ──
class FieldSpec(BaseModel):
    """Specification for a single input field."""
    name: str
    type: Literal["file", "string", "number", "boolean", "object", "array"]
    required: bool = True
    description: str = ""
    
    # For file fields
    accepted_mimetypes: Optional[List[str]] = None
    max_size_mb: Optional[int] = None
    allow_multiple: bool = False
    
    # For string fields
    min_length: Optional[int] = None
    max_length: Optional[int] = None
    pattern: Optional[str] = None
    
    # For number fields
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    integer_only: bool = False
    
    # For enum/string fields
    allowed_values: Optional[List[str]] = None


class EndpointContract(BaseModel):
    """Complete contract for a single evidence endpoint."""
    endpoint: str
    name: str
    description: str
    method: Literal["POST", "GET", "PUT", "DELETE"]
    
    # Input requirements
    required_inputs: List[FieldSpec] = []
    optional_inputs: List[FieldSpec] = []
    
    # MIME types and file formats
    accepted_file_types: List[str] = []
    accepted_file_extensions: List[str] = []
    accepted_mimetypes: List[str] = []
    
    # Size limits
    max_file_size_mb: int = 10
    max_request_size_mb: int = 10
    
    # Authentication and payment
    requires_authentication: bool = False
    requires_payment: bool = False
    
    # Special constraints
    url_requirements: Optional[str] = None
    json_structure: Optional[Dict[str, Any]] = None
    
    # Example valid input
    example_input: Optional[Dict[str, Any]] = None


# ── Contract Generators ──
def image_contract() -> EndpointContract:
    return EndpointContract(
        endpoint="/api/evidence/image",
        name="Image Evidence",
        description="Process and analyze an image file for evidence extraction.",
        method="POST",
        required_inputs=[
            FieldSpec(name="file", type="file", required=True,
                     description="Image file to analyze (up to 2 for comparison)",
                     accepted_mimetypes=ALLOWED_IMAGE_MIME,
                     max_size_mb=MAX_UPLOAD_SIZE_MB,
                     allow_multiple=True),
            FieldSpec(name="claim", type="string", required=False,
                     description="Optional claim or question about the image",
                     max_length=1000),
        ],
        accepted_file_types=["image", "jpg", "jpeg", "png", "webp", "gif", "bmp", "tif", "tiff", "heic", "heif"],
        accepted_file_extensions=[".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tif", ".tiff", ".heic", ".heif"],
        accepted_mimetypes=ALLOWED_IMAGE_MIME,
        max_file_size_mb=MAX_UPLOAD_SIZE_MB,
        example_input={"file": "<image_file>", "claim": "Is this image authentic?"}
    )

def video_contract() -> EndpointContract:
    return EndpointContract(
        endpoint="/api/evidence/video",
        name="Video Evidence",
        description="Process and analyze a video file for evidence extraction.",
        method="POST",
        required_inputs=[
            FieldSpec(name="file", type="file", required=True,
                     description="Video file to analyze",
                     accepted_mimetypes=ALLOWED_VIDEO_MIME,
                     max_size_mb=MAX_UPLOAD_SIZE_MB,
                     allow_multiple=False),
            FieldSpec(name="claim", type="string", required=False,
                     description="Optional claim or question about the video",
                     max_length=1000),
            FieldSpec(name="max_frames", type="number", required=False,
                     description="Maximum number of frames to extract (2-40)",
                     min_value=2, max_value=40, integer_only=True),
        ],
        accepted_file_types=["video", "mp4", "mov", "m4v", "avi", "mkv", "webm", "mpeg", "mpg"],
        accepted_file_extensions=[".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm", ".mpeg", ".mpg"],
        accepted_mimetypes=ALLOWED_VIDEO_MIME,
        max_file_size_mb=MAX_UPLOAD_SIZE_MB,
        example_input={"file": "<video_file>", "claim": "Is this video authentic?", "max_frames": 8}
    )

def audio_contract() -> EndpointContract:
    return EndpointContract(
        endpoint="/api/evidence/audio",
        name="Audio Evidence",
        description="Process and analyze an audio file for evidence extraction.",
        method="POST",
        required_inputs=[
            FieldSpec(name="file", type="file", required=True,
                     description="Audio file to analyze",
                     accepted_mimetypes=ALLOWED_AUDIO_MIME,
                     max_size_mb=MAX_UPLOAD_SIZE_MB,
                     allow_multiple=False),
            FieldSpec(name="claim", type="string", required=False,
                     description="Optional claim or question about the audio",
                     max_length=1000),
        ],
        accepted_file_types=["audio", "mp3", "wav", "m4a", "aac", "flac", "ogg", "opus", "webm"],
        accepted_file_extensions=[".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".webm"],
        accepted_mimetypes=ALLOWED_AUDIO_MIME,
        max_file_size_mb=MAX_UPLOAD_SIZE_MB,
        example_input={"file": "<audio_file>", "claim": "What is being said in this audio?"}
    )

def document_contract() -> EndpointContract:
    return EndpointContract(
        endpoint="/api/evidence/document",
        name="Document Evidence",
        description="Process and analyze a document file for evidence extraction.",
        method="POST",
        required_inputs=[
            FieldSpec(name="file", type="file", required=True,
                     description="Document file to analyze",
                     accepted_mimetypes=ALLOWED_DOCUMENT_MIME,
                     max_size_mb=MAX_UPLOAD_SIZE_MB,
                     allow_multiple=False),
            FieldSpec(name="claim", type="string", required=False,
                     description="Optional claim or question about the document",
                     max_length=1000),
        ],
        accepted_file_types=["document", "pdf", "docx", "doc", "txt", "md", "rtf", "odt"],
        accepted_file_extensions=[".pdf", ".docx", ".doc", ".txt", ".md", ".rtf", ".odt"],
        accepted_mimetypes=ALLOWED_DOCUMENT_MIME,
        max_file_size_mb=MAX_UPLOAD_SIZE_MB,
        example_input={"file": "<document_file>", "claim": "Does this document contain inconsistencies?"}
    )

def authenticity_contract() -> EndpointContract:
    return EndpointContract(
        endpoint="/api/evidence/authenticity",
        name="Authenticity Analysis",
        description="Perform forensic analysis to check media authenticity signals.",
        method="POST",
        required_inputs=[
            FieldSpec(name="file", type="file", required=True,
                     description="Media file to analyze for authenticity",
                     accepted_mimetypes=ALLOWED_IMAGE_MIME + ALLOWED_VIDEO_MIME + ALLOWED_AUDIO_MIME,
                     max_size_mb=MAX_UPLOAD_SIZE_MB,
                     allow_multiple=False),
        ],
        accepted_file_types=["image", "video", "audio"],
        accepted_file_extensions=[".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tif", ".tiff", ".heic", ".heif", ".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm", ".mpeg", ".mpg", ".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".webm"],
        accepted_mimetypes=ALLOWED_IMAGE_MIME + ALLOWED_VIDEO_MIME + ALLOWED_AUDIO_MIME,
        max_file_size_mb=MAX_UPLOAD_SIZE_MB,
        example_input={"file": "<media_file>"}
    )

def url_contract() -> EndpointContract:
    return EndpointContract(
        endpoint="/api/evidence/url",
        name="URL Evidence",
        description="Inspect and analyze a public URL for evidence extraction.",
        method="POST",
        required_inputs=[
            FieldSpec(name="url", type="string", required=True,
                     description="Valid HTTP/HTTPS URL to inspect",
                     pattern=r"^https?://[^\s/$.?#].[^\s]*$",
                     min_length=10, max_length=2048),
            FieldSpec(name="claim", type="string", required=False,
                     description="Optional claim or question about the URL",
                     max_length=1000),
        ],
        url_requirements="Must be a valid HTTP or HTTPS URL (e.g., https://example.com/page)",
        example_input={"url": "https://example.com/listing", "claim": "Is this website legitimate?"}
    )

def structured_contract() -> EndpointContract:
    return EndpointContract(
        endpoint="/api/evidence/structured",
        name="Structured Data Evidence",
        description="Analyze JSON or CSV structured data for evidence extraction.",
        method="POST",
        required_inputs=[
            FieldSpec(name="file", type="file", required=False,
                     description="JSON or CSV file to analyze (alternative to payload)",
                     accepted_mimetypes=ALLOWED_STRUCTURED_MIME,
                     max_size_mb=MAX_UPLOAD_SIZE_MB,
                     allow_multiple=False),
            FieldSpec(name="payload", type="string", required=False,
                     description="JSON or CSV text content (alternative to file)"),
            FieldSpec(name="claim", type="string", required=False,
                     description="Optional claim or question about the data",
                     max_length=1000),
        ],
        accepted_file_types=["json", "csv", "tsv", "jsonl", "xlsx", "xls", "parquet"],
        accepted_file_extensions=[".json", ".csv", ".tsv", ".jsonl", ".xlsx", ".xls", ".parquet"],
        accepted_mimetypes=ALLOWED_STRUCTURED_MIME,
        max_file_size_mb=MAX_UPLOAD_SIZE_MB,
        json_structure={
            "file": "Optional - JSON or CSV file",
            "payload": "Optional - JSON or CSV text content",
            "required": "At least one of 'file' or 'payload' must be provided"
        },
        example_input={"payload": '{"key": "value", "data": [1, 2, 3]}', "claim": "What does this data show?"}
    )

def assess_contract() -> EndpointContract:
    return EndpointContract(
        endpoint="/api/evidence/assess",
        name="Evidence Assessment",
        description="Assess a claim against supplied evidence.",
        method="POST",
        required_inputs=[
            FieldSpec(name="evidence", type="array", required=True,
                     description="Array of evidence objects to assess against",
                     min_length=1),
            FieldSpec(name="claim", type="string", required=False,
                     description="Optional claim to assess (defaults to question from evidence)",
                     max_length=1000),
        ],
        json_structure={
            "evidence": [{"evidence_id": "string", "text": "string"}],
            "claim": "string"
        },
        example_input={"evidence": [{"text": "The seller has 95% positive feedback."}], "claim": "Is this seller legitimate?"}
    )

def contradictions_contract() -> EndpointContract:
    return EndpointContract(
        endpoint="/api/evidence/contradictions",
        name="Contradiction Detection",
        description="Find contradictions in supplied evidence items.",
        method="POST",
        required_inputs=[
            FieldSpec(name="evidence", type="array", required=True,
                     description="Array of evidence objects to check for contradictions",
                     min_length=2),
        ],
        json_structure={"evidence": [{"evidence_id": "string", "text": "string"}]},
        example_input={"evidence": [{"text": "Event at 3 PM"}, {"text": "Event at 5 PM"}]}
    )

def duplicates_contract() -> EndpointContract:
    return EndpointContract(
        endpoint="/api/evidence/duplicates",
        name="Duplicate Detection",
        description="Find duplicate and dependent evidence items.",
        method="POST",
        required_inputs=[
            FieldSpec(name="evidence", type="array", required=True,
                     description="Array of evidence objects to check for duplicates",
                     min_length=1),
        ],
        json_structure={"evidence": [{"evidence_id": "string", "text": "string"}]},
        example_input={"evidence": [{"text": "Company founded in 2010"}, {"text": "Founded in 2010, the company..."}]}
    )

def timeline_contract() -> EndpointContract:
    return EndpointContract(
        endpoint="/api/evidence/timeline",
        name="Timeline Reconstruction",
        description="Reconstruct a timeline from supplied evidence items.",
        method="POST",
        required_inputs=[
            FieldSpec(name="evidence", type="array", required=True,
                     description="Array of evidence objects to extract dates from",
                     min_length=1),
        ],
        json_structure={"evidence": [{"evidence_id": "string", "text": "string"}]},
        example_input={"evidence": [{"text": "Project started Jan 15, 2024"}]}
    )

def gaps_contract() -> EndpointContract:
    return EndpointContract(
        endpoint="/api/evidence/gaps",
        name="Evidence Gaps Analysis",
        description="Identify missing evidence and unresolved questions.",
        method="POST",
        required_inputs=[
            FieldSpec(name="evidence", type="array", required=True,
                     description="Array of evidence objects to analyze for gaps",
                     min_length=0),
            FieldSpec(name="claim", type="string", required=False,
                     description="Optional claim to check for evidence gaps",
                     max_length=1000),
        ],
        json_structure={"evidence": [{"evidence_id": "string", "text": "string"}], "claim": "string"},
        example_input={"evidence": [{"text": "Company has 50 employees"}], "claim": "Is this company stable?"}
    )

def get_all_evidence_contracts() -> List[EndpointContract]:
    """Return the complete contract for all 12 evidence endpoints."""
    return [
        image_contract(),
        video_contract(),
        audio_contract(),
        document_contract(),
        authenticity_contract(),
        url_contract(),
        structured_contract(),
        assess_contract(),
        contradictions_contract(),
        duplicates_contract(),
        timeline_contract(),
        gaps_contract(),
    ]
