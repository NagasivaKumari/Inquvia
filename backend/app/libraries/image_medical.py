"""Medical image investigation boundaries and opt-in enforcement."""
from __future__ import annotations

import re

_MEDICAL_PATTERNS = [
    r"\b(x-?ray|xray|radiograph|mri|ct scan|cat scan|ultrasound|mammogram|pathology)\b",
    r"\b(medical scan|dicom|histolog|biopsy slide|pet scan|echocardiogram)\b",
    r"\b(diagnos(e|is|tic).*image|clinical image|patient scan)\b",
]

MEDICAL_DISCLAIMER = (
    "MEDICAL IMAGE NOTICE: This investigation does NOT provide medical diagnosis, "
    "clinical interpretation, or treatment advice. Medical imaging requires specialized "
    "PACS/DICOM systems and licensed clinicians. Any observations here are generic file/visual "
    "analysis only — not a medical assessment."
)

OPT_IN_PHRASES = (
    "medical investigation opt-in",
    "medical opt-in",
    "i consent to medical image analysis",
)


def is_medical_question(question: str) -> bool:
    q = (question or "").lower()
    return any(re.search(p, q, re.I) for p in _MEDICAL_PATTERNS)


def medical_opt_in(question: str, *, explicit_flag: bool = False) -> bool:
    if explicit_flag:
        return True
    q = (question or "").lower()
    return any(phrase in q for phrase in OPT_IN_PHRASES)


def require_medical_opt_in(question: str, *, explicit_flag: bool = False) -> None:
    if is_medical_question(question) and not medical_opt_in(question, explicit_flag=explicit_flag):
        raise ValueError(
            "Medical image analysis requires explicit opt-in. Add 'medical investigation opt-in' "
            "to your question or set medicalOptIn=true in the request."
        )
