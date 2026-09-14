import logging
from typing import Dict, Type, Optional, List
from .evidence_types import EvidenceCheck

logger = logging.getLogger(__name__)

class EvidenceRegistry:
    _checks: Dict[str, EvidenceCheck] = {}

    @classmethod
    def register(cls, check_id: str, check_instance: EvidenceCheck):
        cls._checks[check_id] = check_instance
        logger.info(f"Registered evidence check: {check_id}")

    @classmethod
    def get_check(cls, check_id: str) -> Optional[EvidenceCheck]:
        return cls._checks.get(check_id)

    @classmethod
    def list_checks(cls) -> List[str]:
        return list(cls._checks.keys())
