"""
Industry-specific prospector implementations.

Each industry module provides a prospector class that inherits from
IndustryProspector and implements the data fetching and parsing logic
for that industry's data sources.
"""

from .trucking import TruckingProspector

__all__ = ["TruckingProspector"]
