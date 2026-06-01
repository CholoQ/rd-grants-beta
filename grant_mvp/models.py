from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

@dataclass
class ParsedProfile:
    company_phases: List[str] = field(default_factory=list)
    intents: List[str] = field(default_factory=list)
    background_intents: List[str] = field(default_factory=list)
    negative_intents: List[str] = field(default_factory=list)
    expense_types: List[str] = field(default_factory=list)
    region: Optional[str] = None
    employee_count: Optional[int] = None
    entity_type: Optional[str] = None
    keywords: List[str] = field(default_factory=list)
    sectors: List[str] = field(default_factory=list)
    negative_sectors: List[str] = field(default_factory=list)
    budget_min: Optional[int] = None
    is_startup: bool = False
    university_origin: bool = False
    rationale: str = ""
    extracted_tags: List[str] = field(default_factory=list)
    missing_fields: List[str] = field(default_factory=list)
    followup_question: Optional[str] = None
