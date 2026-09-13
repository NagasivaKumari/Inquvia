"""
Authoritative input contract validation for evidence endpoints.

This module provides reusable validators derived from the contracts
defined in contract_registry.py, and standardized error response formats.
"""
from enum import Enum
from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, Field, field_validator, model_validator
from .contract_registry import MAX_UPLOAD_SIZE_MB, get_all_evidence_contracts

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
                    file_extensions=[".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tif", ".tiff", ".heic", ".heif", ".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm", ".mpeg", ".mpg", ".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".pdf", ".docx", ".doc", ".txt", ".md", ".rtf", ".odt", ".csv", ".tsv", ".json", ".jsonl", ".xlsx", ".xls", ".parquet"]
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
                    accepted_extensions.extend([".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tif", ".tiff", ".heic", ".heif"])
                elif mime.startswith("video/"):
                    accepted_extensions.extend([".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm", ".mpeg", ".mpg"])
                elif mime.startswith("audio/"):
                    accepted_extensions.extend([".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".webm"])
                elif mime in ("application/pdf", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "application/msword", "text/plain", "text/markdown", "application/rtf", "application/vnd.oasis.opendocument.text"):
                    accepted_extensions.extend([".pdf", ".docx", ".doc", ".txt", ".md", ".rtf", ".odt"])
                elif mime in ("text/csv", "text/tab-separated-values", "application/json", "application/x-jsonlines", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "application/vnd.ms-excel", "application/x-parquet"):
                    accepted_extensions.extend([".csv", ".tsv", ".json", ".jsonl", ".xlsx", ".xls", ".parquet"])
            
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
