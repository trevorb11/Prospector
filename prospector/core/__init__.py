"""Core components for the Prospector framework."""

from .base import IndustryProspector, ProspectRecord
from .scoring import ScoringEngine, ScoringRule
from .enricher import LeadEnricher
from .mca_scoring import MCAScorer, MCAIndustryProfile, detect_industry_profile
from .ucc_crossref import UCCCrossReferencer

__all__ = [
    "IndustryProspector",
    "ProspectRecord",
    "ScoringEngine",
    "ScoringRule",
    "LeadEnricher",
    "MCAScorer",
    "MCAIndustryProfile",
    "detect_industry_profile",
    "UCCCrossReferencer",
]
