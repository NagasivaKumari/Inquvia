"""
Authoritative input contract schema and validation library for evidence endpoints.

This module provides:
1. An authoritative contract schema for all 12 evidence endpoints
2. Reusable validators derived from the contracts
3. Standardized error response format

The contract is the single source of truth - both validation and frontend display
derive from it.
"""
from enum import Enum
from typing import Any, Dict, List, Optional, Literal, Union
from pydantic import BaseModel, Field, field_validator, model_validator
from fastapi import HTTPException


# ── Constants (derived from config.py) ──
MAX_UPLOAD_SIZE_MB = 10
MAX_UPLOAD_SIZE = MAX_UPLOAD_SIZE_MB * 1024 * 1024

ALLOWED_IMAGE_MIME = [
    "image/jpeg", "image/png", "image/webp", "image/gif"
]
ALLOWED_VIDEO_MIME = [
    "video/mp4", "video/webm"
]
ALLOWED_AUDIO_MIME = [
    "audio/mpeg", "audio/wav", "audio/mp3", "audio/ogg"
]
ALLOWED_DOCUMENT_MIME = [
    "application/pdf", "text/plain", "text/csv"
]
ALLOWED_STRUCTURED_MIME = [
    "application/json", "text/plain", "text/csv"
]

ALLOWED_MIME = (
    ALLOWED_IMAGE_MIME +
    ALLOWED_VIDEO_MIME +
    ALLOWED_AUDIO_MIME +
    ALLOWED_DOCUMENT_MIME +
    ALLOWED_STRUCTURED_MIME
)


# ── Standardized Error Response Format ──
class ErrorCode(str, Enum):
    # Validation errors (4xx)
    MISSING_REQUIRED_FIELD = "MISSING_REQUIRED_FIELD"
    INVALID_FIELD_VALUE = "INVALID_FIELD_VALUE"
    UNSUPPORTED_FILE_TYPE = "UNSUPPORTED_FILE_TYPE"
    FILE_TOO_LARGE = "FILE_TOO_LARGE"
    INVALID_URL = "INVALID_URL"
    INVALID_JSON = "INVALID_JSON"
    INVALID_CSV = "INVALID_CSV"
    INVALID_BODY_SCHEMA = "INVALID_BODY_SCHEMA"
    
    # Authentication/Authorization errors (401/403)
    UNAUTHORIZED = "UNAUTHORIZED"
    FORBIDDEN = "FORBIDDEN"
    
    # Server errors (5xx) - these should not be exposed to users
    INTERNAL_ERROR = "INTERNAL_ERROR"


class ErrorDetails(BaseModel):
    """Additional machine-readable error details."""
    field: Optional[str] = None
    received: Optional[Any] = None
    expected: Optional[Any] = None
    accepted_values: Optional[List[str]] = None
    max_size_mb: Optional[int] = None
    received_size_bytes: Optional[int] = None
    mime_type: Optional[str] = None
    accepted_mimetypes: Optional[List[str]] = None
    file_extensions: Optional[List[str]] = None


class ErrorResponse(BaseModel):
    """Standardized error response for user-facing validation errors."""
    error: str = Field(..., description="Error code (uppercase, underscore-separated)")
    message: str = Field(..., description="Human-readable error message")
    field: Optional[str] = Field(None, description="Field that caused the error")
    details: Optional[ErrorDetails] = Field(None, description="Additional error details")


# ── Input Contract Schema ──
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


# ── All 12 Evidence Endpoint Contracts ──
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


def image_contract() -> EndpointContract:
    """Contract for /api/evidence/image endpoint."""
    return EndpointContract(
        endpoint="/api/evidence/image",
        name="Image Evidence",
        description="Process and analyze an image file for evidence extraction.",
        method="POST",
        required_inputs=[
            FieldSpec(name="file", type="file", required=True,
                     description="Image file to analyze",
                     accepted_mimetypes=ALLOWED_IMAGE_MIME,
                     max_size_mb=MAX_UPLOAD_SIZE_MB,
                     allow_multiple=False),
            FieldSpec(name="claim", type="string", required=False,
                     description="Optional claim or question about the image",
                     max_length=1000),
        ],
        accepted_file_types=["image", "jpeg", "jpg", "png", "webp", "gif"],
        accepted_file_extensions=[".jpg", ".jpeg", ".png", ".webp", ".gif"],
        accepted_mimetypes=ALLOWED_IMAGE_MIME,
        max_file_size_mb=MAX_UPLOAD_SIZE_MB,
        requires_authentication=False,
        requires_payment=False,
        example_input={
            "file": "<image_file>",
            "claim": "Is this image authentic?"
        }
    )


def video_contract() -> EndpointContract:
    """Contract for /api/evidence/video endpoint."""
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
        accepted_file_types=["video", "mp4", "webm"],
        accepted_file_extensions=[".mp4", ".webm"],
        accepted_mimetypes=ALLOWED_VIDEO_MIME,
        max_file_size_mb=MAX_UPLOAD_SIZE_MB,
        requires_authentication=False,
        requires_payment=False,
        example_input={
            "file": "<video_file>",
            "claim": "Is this video authentic?",
            "max_frames": 8
        }
    )


def audio_contract() -> EndpointContract:
    """Contract for /api/evidence/audio endpoint."""
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
        accepted_file_types=["audio", "mp3", "wav", "ogg"],
        accepted_file_extensions=[".mp3", ".wav", ".ogg"],
        accepted_mimetypes=ALLOWED_AUDIO_MIME,
        max_file_size_mb=MAX_UPLOAD_SIZE_MB,
        requires_authentication=False,
        requires_payment=False,
        example_input={
            "file": "<audio_file>",
            "claim": "What is being said in this audio?"
        }
    )


def document_contract() -> EndpointContract:
    """Contract for /api/evidence/document endpoint."""
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
        accepted_file_types=["document", "pdf", "txt", "csv"],
        accepted_file_extensions=[".pdf", ".txt", ".csv"],
        accepted_mimetypes=ALLOWED_DOCUMENT_MIME,
        max_file_size_mb=MAX_UPLOAD_SIZE_MB,
        requires_authentication=False,
        requires_payment=False,
        example_input={
            "file": "<document_file>",
            "claim": "Does this document contain inconsistencies?"
        }
    )


def authenticity_contract() -> EndpointContract:
    """Contract for /api/evidence/authenticity endpoint."""
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
        accepted_file_extensions=[".jpg", ".jpeg", ".png", ".webp", ".gif", ".mp4", ".webm", ".mp3", ".wav", ".ogg"],
        accepted_mimetypes=ALLOWED_IMAGE_MIME + ALLOWED_VIDEO_MIME + ALLOWED_AUDIO_MIME,
        max_file_size_mb=MAX_UPLOAD_SIZE_MB,
        requires_authentication=False,
        requires_payment=False,
        example_input={
            "file": "<media_file>"
        }
    )


def url_contract() -> EndpointContract:
    """Contract for /api/evidence/url endpoint."""
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
        requires_authentication=False,
        requires_payment=False,
        example_input={
            "url": "https://example.com/listing",
            "claim": "Is this website legitimate?"
        }
    )


def structured_contract() -> EndpointContract:
    """Contract for /api/evidence/structured endpoint."""
    return EndpointContract(
        endpoint="/api/evidence/structured",
        name="Structured Data Evidence",
        description="Analyze JSON or CSV structured data for evidence extraction.",
        method="POST",
        required_inputs=[
            FieldSpec(name="file", type="file", required=False,
                     description="JSON or CSV file to analyze (alternative to payload)",
                     accepted_mimetypes=["application/json", "text/plain", "text/csv"],
                     max_size_mb=MAX_UPLOAD_SIZE_MB,
                     allow_multiple=False),
            FieldSpec(name="payload", type="string", required=False,
                     description="JSON or CSV text content (alternative to file)"),
            FieldSpec(name="claim", type="string", required=False,
                     description="Optional claim or question about the data",
                     max_length=1000),
        ],
        accepted_file_types=["json", "csv"],
        accepted_file_extensions=[".json", ".csv"],
        accepted_mimetypes=["application/json", "text/plain", "text/csv"],
        max_file_size_mb=MAX_UPLOAD_SIZE_MB,
        json_structure={
            "file": "Optional - JSON or CSV file",
            "payload": "Optional - JSON or CSV text content",
            "required": "At least one of 'file' or 'payload' must be provided"
        },
        requires_authentication=False,
        requires_payment=False,
        example_input={
            "payload": '{"key": "value", "data": [1, 2, 3]}',
            "claim": "What does this data show?"
        }
    )


def assess_contract() -> EndpointContract:
    """Contract for /api/evidence/assess endpoint."""
    return EndpointContract(
        endpoint="/api/evidence/assess",
        name="Evidence Assessment",
        description="Assess a claim against supplied evidence.",
        method="POST",
        required_inputs=[
            FieldSpec(name="evidence", type="array", required=True,
                     description="Array of evidence objects to assess against",
                     min_items=1),
            FieldSpec(name="claim", type="string", required=False,
                     description="Optional claim to assess (defaults to question from evidence)",
                     max_length=1000),
        ],
        accepted_mimetypes=[],  # No file uploads, JSON only
        json_structure={
            "evidence": [
                {
                    "evidence_id": "string - Optional ID for the evidence item",
                    "text": "string - The evidence text/content",
                    "finding": "string - Optional finding/summary",
                    "claim": "string - Optional claim",
                    "type": "string - Optional type (default: 'text')",
                    "source": "string - Optional source URL or description",
                    "confidence": "number - Optional confidence score 0-1",
                    "signal": "string - Optional signal level ('certain', 'uncertain', 'contradictory')",
                    "metadata": "object - Optional additional metadata"
                }
            ],
            "claim": "string - Optional claim to assess"
        },
        requires_authentication=False,
        requires_payment=False,
        example_input={
            "evidence": [
                {
                    "text": "The seller has 95% positive feedback.",
                    "source": "https://example.com/seller"
                }
            ],
            "claim": "Is this seller legitimate?"
        }
    )


def contradictions_contract() -> EndpointContract:
    """Contract for /api/evidence/contradictions endpoint."""
    return EndpointContract(
        endpoint="/api/evidence/contradictions",
        name="Contradiction Detection",
        description="Find contradictions in supplied evidence items.",
        method="POST",
        required_inputs=[
            FieldSpec(name="evidence", type="array", required=True,
                     description="Array of evidence objects to check for contradictions",
                     min_items=2),
        ],
        accepted_mimetypes=[],  # No file uploads, JSON only
        json_structure={
            "evidence": [
                {
                    "evidence_id": "string - Optional ID",
                    "text": "string - Evidence text",
                    "finding": "string - Optional finding",
                    "claim": "string - Optional claim",
                    "type": "string - Optional type",
                    "source": "string - Optional source",
                    "confidence": "number - Optional confidence",
                    "signal": "string - Optional signal",
                    "metadata": "object - Optional metadata"
                }
            ]
        },
        requires_authentication=False,
        requires_payment=False,
        example_input={
            "evidence": [
                {"text": "The event occurred at 3:00 PM"},
                {"text": "The event occurred at 5:00 PM"}
            ]
        }
    )


def duplicates_contract() -> EndpointContract:
    """Contract for /api/evidence/duplicates endpoint."""
    return EndpointContract(
        endpoint="/api/evidence/duplicates",
        name="Duplicate Detection",
        description="Find duplicate and dependent evidence items.",
        method="POST",
        required_inputs=[
            FieldSpec(name="evidence", type="array", required=True,
                     description="Array of evidence objects to check for duplicates",
                     min_items=1),
        ],
        accepted_mimetypes=[],  # No file uploads, JSON only
        json_structure={
            "evidence": [
                {
                    "evidence_id": "string - Optional ID",
                    "text": "string - Evidence text",
                    "finding": "string - Optional finding",
                    "claim": "string - Optional claim",
                    "type": "string - Optional type",
                    "source": "string - Optional source",
                    "confidence": "number - Optional confidence",
                    "signal": "string - Optional signal",
                    "metadata": "object - Optional metadata"
                }
            ]
        },
        requires_authentication=False,
        requires_payment=False,
        example_input={
            "evidence": [
                {"text": "The company was founded in 2010"},
                {"text": "Founded in 2010, the company has grown significantly"}
            ]
        }
    )


def timeline_contract() -> EndpointContract:
    """Contract for /api/evidence/timeline endpoint."""
    return EndpointContract(
        endpoint="/api/evidence/timeline",
        name="Timeline Reconstruction",
        description="Reconstruct a timeline from supplied evidence items.",
        method="POST",
        required_inputs=[
            FieldSpec(name="evidence", type="array", required=True,
                     description="Array of evidence objects to extract dates from",
                     min_items=1),
        ],
        accepted_mimetypes=[],  # No file uploads, JSON only
        json_structure={
            "evidence": [
                {
                    "evidence_id": "string - Optional ID",
                    "text": "string - Evidence text (dates will be extracted from here)",
                    "finding": "string - Optional finding",
                    "claim": "string - Optional claim",
                    "type": "string - Optional type",
                    "source": "string - Optional source",
                    "confidence": "number - Optional confidence",
                    "signal": "string - Optional signal",
                    "metadata": "object - Optional metadata"
                }
            ]
        },
        requires_authentication=False,
        requires_payment=False,
        example_input={
            "evidence": [
                {"text": "The project started on January 15, 2024"},
                {"text": "Phase 2 began on March 1, 2024"}
            ]
        }
    )


def gaps_contract() -> EndpointContract:
    """Contract for /api/evidence/gaps endpoint."""
    return EndpointContract(
        endpoint="/api/evidence/gaps",
        name="Evidence Gaps Analysis",
        description="Identify missing evidence and unresolved questions.",
        method="POST",
        required_inputs=[
            FieldSpec(name="evidence", type="array", required=True,
                     description="Array of evidence objects to analyze for gaps",
                     min_items=0),
            FieldSpec(name="claim", type="string", required=False,
                     description="Optional claim to check for evidence gaps",
                     max_length=1000),
        ],
        accepted_mimetypes=[],  # No file uploads, JSON only
        json_structure={
            "evidence": [
                {
                    "evidence_id": "string - Optional ID",
                    "text": "string - Evidence text",
                    "finding": "string - Optional finding",
                    "claim": "string - Optional claim",
                    "type": "string - Optional type",
                    "source": "string - Optional source",
                    "confidence": "number - Optional confidence",
                    "signal": "string - Optional signal",
                    "metadata": "object - Optional metadata"
                }
            ],
            "claim": "string - Optional claim to check"
        },
        requires_authentication=False,
        requires_payment=False,
        example_input={
            "evidence": [
                {"text": "The company has 50 employees"}
            ],
            "claim": "Is this company stable?"
        }
    )


# ── Reusable Validators with CLEAR USER-FRIENDLY MESSAGES ──
class EvidenceValidator:
    """Collection of reusable validators for evidence endpoints."""
    
    @staticmethod
    def validate_file_upload(
        content_type: Optional[str],
        size: int,
        allowed_mimetypes: List[str],
        max_size_mb: int = MAX_UPLOAD_SIZE_MB
    ) -> tuple[bool, Optional[ErrorResponse]]:
        """
        Validate a file upload against contract requirements.
        Returns user-friendly error messages.
        
        Returns:
            tuple: (is_valid, error_response or None)
        """
        # Check for empty/null file
        if not content_type or content_type == "":
            return False, ErrorResponse(
                error=ErrorCode.UNSUPPORTED_FILE_TYPE,
                message="You haven't selected a file. Please choose a file to upload.",
                field="file",
                details=ErrorDetails(
                    file_extensions=[".jpg", ".png", ".webp", ".gif", ".mp4", ".webm", ".mp3", ".wav", ".ogg", ".pdf", ".txt", ".csv", ".json"]
                )
            )
        
        # Check for empty file (0 bytes)
        if size == 0:
            return False, ErrorResponse(
                error=ErrorCode.FILE_TOO_LARGE,
                message="The file you selected is empty. Please choose a valid file with content.",
                field="file",
                details=ErrorDetails(
                    received_size_bytes=0,
                    max_size_mb=max_size_mb
                )
            )
        
        # Check file size
        if size > max_size_mb * 1024 * 1024:
            actual_size_mb = size / (1024 * 1024)
            return False, ErrorResponse(
                error=ErrorCode.FILE_TOO_LARGE,
                message=f"The file is too large. Maximum file size is {max_size_mb}MB, but your file is {actual_size_mb:.1f}MB. Please try a smaller file.",
                field="file",
                details=ErrorDetails(
                    received_size_bytes=size,
                    max_size_mb=max_size_mb
                )
            )
        
        # Check file type
        if content_type not in allowed_mimetypes:
            # Build helpful message about what files are accepted
            accepted_extensions = []
            for mime in allowed_mimetypes:
                if mime.startswith("image/"):
                    accepted_extensions.extend([".jpg", ".jpeg", ".png", ".webp", ".gif"])
                elif mime.startswith("video/"):
                    accepted_extensions.extend([".mp4", ".webm"])
                elif mime.startswith("audio/"):
                    accepted_extensions.extend([".mp3", ".wav", ".ogg"])
                elif mime == "application/pdf":
                    accepted_extensions.append(".pdf")
                elif mime == "text/plain" or mime == "text/csv":
                    accepted_extensions.extend([".txt", ".csv"])
                elif mime == "application/json":
                    accepted_extensions.append(".json")
            
            # Clean up duplicates
            accepted_extensions = list(set(accepted_extensions))
            
            return False, ErrorResponse(
                error=ErrorCode.UNSUPPORTED_FILE_TYPE,
                message=f"This endpoint only accepts specific file types. Please upload: {', '.join(accepted_extensions)} files.",
                field="file",
                details=ErrorDetails(
                    mime_type=content_type,
                    accepted_mimetypes=allowed_mimetypes,
                    file_extensions=accepted_extensions
                )
            )
        
        return True, None
    
    @staticmethod
    def validate_url(url: Optional[str]) -> tuple[bool, Optional[ErrorResponse]]:
        """
        Validate a URL input.
        Returns user-friendly error messages.
        
        Returns:
            tuple: (is_valid, error_response or None)
        """
        if not url or not url.strip():
            return False, ErrorResponse(
                error=ErrorCode.INVALID_URL,
                message="Please enter a URL. This field is required.",
                field="url",
                details=ErrorDetails(
                    expected="A URL starting with http:// or https://"
                )
            )
        
        url = url.strip()
        
        if not (url.startswith("http://") or url.startswith("https://")):
            return False, ErrorResponse(
                error=ErrorCode.INVALID_URL,
                message="The URL must start with 'http://' or 'https://'. For example: https://example.com",
                field="url",
                details=ErrorDetails(
                    received=url,
                    expected="URL starting with http:// or https://"
                )
            )
        
        return True, None
    
    @staticmethod
    def validate_json_payload(payload: Optional[str]) -> tuple[bool, Optional[ErrorResponse]]:
        """
        Validate a JSON payload string.
        Returns user-friendly error messages.
        
        Returns:
            tuple: (is_valid, error_response or None)
        """
        if not payload or not payload.strip():
            return False, ErrorResponse(
                error=ErrorCode.INVALID_JSON,
                message="Please enter a JSON payload or upload a file. This field is required.",
                field="payload",
                details=ErrorDetails(
                    expected="Valid JSON or CSV content"
                )
            )
        
        try:
            import json
            json.loads(payload)
            return True, None
        except json.JSONDecodeError as e:
            return False, ErrorResponse(
                error=ErrorCode.INVALID_JSON,
                message=f"The JSON data is not valid. Please check your JSON format and try again.",
                field="payload",
                details=ErrorDetails(
                    received=payload[:200],
                    expected="Valid JSON format"
                )
            )
    
    @staticmethod
    def validate_required_field(value: Any, field_name: str, friendly_name: str = "") -> tuple[bool, Optional[ErrorResponse]]:
        """
        Validate that a required field has a value.
        Returns user-friendly error messages.
        
        Args:
            value: The field value to check
            field_name: The internal field name
            friendly_name: A user-friendly name for the field (e.g., "evidence array" instead of "evidence")
            
        Returns:
            tuple: (is_valid, error_response or None)
        """
        friendly = friendly_name or field_name
        
        if value is None or (isinstance(value, str) and not value.strip()):
            return False, ErrorResponse(
                error=ErrorCode.MISSING_REQUIRED_FIELD,
                message=f"Please provide {friendly}. This field is required.",
                field=field_name,
                details=ErrorDetails(
                    expected=f"Non-empty {friendly_name or field_name}"
                )
            )
        
        return True, None
    
    @staticmethod
    def validate_evidence_array_length(evidence: Any, min_items: int, endpoint_name: str) -> tuple[bool, Optional[ErrorResponse]]:
        """
        Validate evidence array has minimum required items.
        Returns user-friendly error messages.
        
        Args:
            evidence: The evidence array
            min_items: Minimum required items
            endpoint_name: Name of the endpoint for the error message
            
        Returns:
            tuple: (is_valid, error_response or None)
        """
        if not isinstance(evidence, list):
            return False, ErrorResponse(
                error=ErrorCode.INVALID_BODY_SCHEMA,
                message=f"The evidence must be a list of items. Please make sure you're sending an array.",
                field="evidence",
                details=ErrorDetails(
                    expected=f"an array with at least {min_items} item(s)"
                )
            )
        
        if len(evidence) < min_items:
            return False, ErrorResponse(
                error=ErrorCode.MISSING_REQUIRED_FIELD,
                message=f"You need at least {min_items} evidence item(s) to use {endpoint_name}. Please add more items.",
                field="evidence",
                details=ErrorDetails(
                    received=len(evidence),
                    expected=f"at least {min_items} item(s)"
                )
            )
        
        return True, None
    
    @staticmethod
    def validate_number_field(value: Any, field_name: str, min_val: int, max_val: int, friendly_name: str = "") -> tuple[bool, Optional[ErrorResponse]]:
        """
        Validate a number field has a valid value within range.
        Returns user-friendly error messages.
        
        Returns:
            tuple: (is_valid, error_response or None)
        """
        if not isinstance(value, (int, float)):
            return False, ErrorResponse(
                error=ErrorCode.INVALID_FIELD_VALUE,
                message=f"Please enter a number for {friendly_name or field_name}.",
                field=field_name,
                details=ErrorDetails(
                    expected=f"a number between {min_val} and {max_val}"
                )
            )
        
        if value < min_val or value > max_val:
            return False, ErrorResponse(
                error=ErrorCode.INVALID_FIELD_VALUE,
                message=f"{friendly_name or field_name} must be between {min_val} and {max_val}. You entered {value}.",
                field=field_name,
                details=ErrorDetails(
                    received=value,
                    expected=f"a number between {min_val} and {max_val}"
                )
            )
        
        return True, None


# ── Pydantic Models for Request Bodies ──
class URLEvidenceRequest(BaseModel):
    """Request model for /api/evidence/url endpoint."""
    url: str = Field(..., description="Valid HTTP/HTTPS URL to inspect")
    claim: str = Field(default="", description="Optional claim or question about the URL")
    
    @field_validator("url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Please enter a URL. This field is required.")
        if not (v.strip().startswith("http://") or v.strip().startswith("https://")):
            raise ValueError("The URL must start with 'http://' or 'https://'. For example: https://example.com")
        return v.strip()


class StructuredEvidenceRequest(BaseModel):
    """Request model for /api/evidence/structured endpoint."""
    file: Optional[str] = Field(default=None, description="File ID (if file is uploaded)")
    payload: Optional[str] = Field(default=None, description="JSON or CSV text content")
    claim: str = Field(default="", description="Optional claim or question about the data")
    
    @model_validator(mode="after")
    def validate_at_least_one_payload(self):
        if not self.payload and not self.file:
            raise ValueError("Please provide either a JSON/CSV file or paste the content directly. At least one is required.")
        return self


class AssessmentEvidenceRequest(BaseModel):
    """Request model for /api/evidence/assess endpoint."""
    evidence: List[Dict[str, Any]] = Field(..., min_length=1, description="Array of evidence objects")
    claim: str = Field(default="", description="Optional claim to assess")


class ContradictionsEvidenceRequest(BaseModel):
    """Request model for /api/evidence/contradictions endpoint."""
    evidence: List[Dict[str, Any]] = Field(..., min_length=2, description="Array of evidence objects")


class DuplicatesEvidenceRequest(BaseModel):
    """Request model for /api/evidence/duplicates endpoint."""
    evidence: List[Dict[str, Any]] = Field(..., min_length=1, description="Array of evidence objects")


class TimelineEvidenceRequest(BaseModel):
    """Request model for /api/evidence/timeline endpoint."""
    evidence: List[Dict[str, Any]] = Field(..., min_length=1, description="Array of evidence objects")


class GapsEvidenceRequest(BaseModel):
    """Request model for /api/evidence/gaps endpoint."""
    evidence: List[Dict[str, Any]] = Field(default_factory=list, description="Array of evidence objects")
    claim: str = Field(default="", description="Optional claim to check")


# ── Exception Handlers ──
class EvidenceValidationError(Exception):
    """Custom exception for evidence validation errors."""
    
    def __init__(self, error_response: ErrorResponse):
        self.error_response = error_response
        super().__init__(error_response.message)
