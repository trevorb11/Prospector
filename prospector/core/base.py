"""
Base classes for industry-specific prospect finders.

This module provides the abstract base class that all industry-specific
prospectors should inherit from, ensuring a consistent interface across
different data sources.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from datetime import datetime
import pandas as pd


@dataclass
class ProspectRecord:
    """
    Standardized prospect record that works across all industries.

    This provides a common format regardless of the data source,
    making it easy to process, score, and export prospects.
    """
    # Core identification
    company_name: str
    dba_name: Optional[str] = None
    industry_id: Optional[str] = None  # e.g., DOT number, EIN, etc.

    # Contact information
    phone: Optional[str] = None
    email: Optional[str] = None
    website: Optional[str] = None

    # Physical address
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    zip_code: Optional[str] = None

    # Mailing address (if different)
    mailing_address: Optional[str] = None
    mailing_city: Optional[str] = None
    mailing_state: Optional[str] = None
    mailing_zip: Optional[str] = None

    # Business metrics (industry-specific)
    business_size_metric: Optional[float] = None  # e.g., trucks, employees, revenue
    business_size_label: Optional[str] = None     # e.g., "Trucks", "Employees"
    employee_count: Optional[int] = None
    years_in_business: Optional[float] = None

    # Industry-specific data
    industry_data: Dict[str, Any] = field(default_factory=dict)

    # Scoring
    prospect_score: int = 0
    score_breakdown: Dict[str, int] = field(default_factory=dict)

    # Metadata
    source: Optional[str] = None
    retrieved_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for export."""
        base_dict = {
            "Score": self.prospect_score,
            "Company Name": self.company_name,
            "DBA Name": self.dba_name or "",
            "Phone": self.phone or "",
            "Email": self.email or "",
            "Website": self.website or "",
            "Address": self.address or "",
            "City": self.city or "",
            "State": self.state or "",
            "ZIP": self.zip_code or "",
            "Industry ID": self.industry_id or "",
            self.business_size_label or "Business Size": self.business_size_metric or "",
            "Employees": self.employee_count or "",
            "Years in Business": self.years_in_business or "",
            "Source": self.source or "",
        }

        # Add industry-specific fields
        for key, value in self.industry_data.items():
            base_dict[key] = value

        return base_dict


class IndustryProspector(ABC):
    """
    Abstract base class for industry-specific prospect finders.

    Subclasses must implement:
    - fetch_prospects(): Retrieve raw data from the industry data source
    - parse_record(): Convert raw API data to ProspectRecord
    - get_industry_name(): Return the industry name

    Optional overrides:
    - get_scoring_rules(): Return industry-specific scoring rules
    - enrich_record(): Add additional data to a prospect
    """

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize the prospector with configuration.

        Args:
            config: Dictionary containing settings like target_states,
                   size filters, API keys, etc.
        """
        self.config = config
        self._prospects: List[ProspectRecord] = []

    @abstractmethod
    def get_industry_name(self) -> str:
        """Return the name of this industry (e.g., 'Trucking', 'Construction')."""
        pass

    @abstractmethod
    def fetch_prospects(self) -> List[Dict[str, Any]]:
        """
        Fetch raw prospect data from the industry data source.

        Returns:
            List of raw records from the API/database
        """
        pass

    @abstractmethod
    def parse_record(self, raw_record: Dict[str, Any]) -> ProspectRecord:
        """
        Convert a raw API record to a standardized ProspectRecord.

        Args:
            raw_record: Raw data from the industry API

        Returns:
            Standardized ProspectRecord
        """
        pass

    def get_scoring_rules(self) -> List[Dict[str, Any]]:
        """
        Return industry-specific scoring rules.

        Override this to provide custom scoring logic for the industry.
        Default returns empty list (uses only base scoring).

        Returns:
            List of scoring rule dictionaries
        """
        return []

    def enrich_record(self, record: ProspectRecord) -> ProspectRecord:
        """
        Optionally enrich a record with additional data.

        Override this to add data from additional sources.
        Default returns the record unchanged.

        Args:
            record: The prospect record to enrich

        Returns:
            Enriched prospect record
        """
        return record

    def run(self, score: bool = True, enrich: bool = False) -> List[ProspectRecord]:
        """
        Execute the full prospect finding pipeline.

        Args:
            score: Whether to score the prospects
            enrich: Whether to enrich with additional data

        Returns:
            List of ProspectRecord objects
        """
        from .scoring import ScoringEngine

        # Fetch raw data
        raw_records = self.fetch_prospects()

        # Parse into standardized records
        self._prospects = []
        for raw in raw_records:
            try:
                record = self.parse_record(raw)
                record.source = self.get_industry_name()
                self._prospects.append(record)
            except Exception as e:
                # Log but continue on parse errors
                print(f"Warning: Failed to parse record: {e}")
                continue

        # Optionally enrich
        if enrich:
            self._prospects = [self.enrich_record(r) for r in self._prospects]

        # Score prospects
        if score:
            scoring_engine = ScoringEngine(self.get_scoring_rules())
            self._prospects = [scoring_engine.score(r) for r in self._prospects]
            # Sort by score descending
            self._prospects.sort(key=lambda x: x.prospect_score, reverse=True)

        return self._prospects

    def to_dataframe(self) -> pd.DataFrame:
        """Convert prospects to a pandas DataFrame."""
        if not self._prospects:
            return pd.DataFrame()
        return pd.DataFrame([p.to_dict() for p in self._prospects])

    def export_csv(self, filepath: str, hot_threshold: int = 70) -> None:
        """
        Export prospects to CSV file(s).

        Args:
            filepath: Path to the output CSV file
            hot_threshold: Score threshold for "hot" prospects file
        """
        df = self.to_dataframe()
        if df.empty:
            print("No prospects to export!")
            return

        # Export all prospects
        df.to_csv(filepath, index=False)
        print(f"Exported {len(df)} prospects to {filepath}")

        # Export hot prospects
        hot_df = df[df["Score"] >= hot_threshold]
        if not hot_df.empty:
            hot_filepath = filepath.replace(".csv", "_HOT.csv")
            hot_df.to_csv(hot_filepath, index=False)
            print(f"Exported {len(hot_df)} hot prospects to {hot_filepath}")

    def export_excel(self, filepath: str, hot_threshold: int = 70) -> None:
        """
        Export prospects to Excel file with multiple sheets.

        Args:
            filepath: Path to the output Excel file
            hot_threshold: Score threshold for "hot" prospects sheet
        """
        df = self.to_dataframe()
        if df.empty:
            print("No prospects to export!")
            return

        with pd.ExcelWriter(filepath, engine="openpyxl") as writer:
            # All prospects
            df.to_excel(writer, sheet_name="All Prospects", index=False)

            # Hot prospects
            hot_df = df[df["Score"] >= hot_threshold]
            if not hot_df.empty:
                hot_df.to_excel(writer, sheet_name="Hot Prospects (70+)", index=False)

            # Medium prospects
            medium_df = df[(df["Score"] >= 50) & (df["Score"] < hot_threshold)]
            if not medium_df.empty:
                medium_df.to_excel(writer, sheet_name="Medium (50-69)", index=False)

            # Summary stats
            summary_data = {
                "Metric": [
                    "Total Prospects",
                    "Hot Prospects (70+)",
                    "Medium Prospects (50-69)",
                    "Lower Prospects (<50)",
                    "Average Score",
                    "With Phone Number",
                ],
                "Value": [
                    len(df),
                    len(hot_df),
                    len(medium_df),
                    len(df[df["Score"] < 50]),
                    round(df["Score"].mean(), 1),
                    len(df[df["Phone"].notna() & (df["Phone"] != "")]),
                ],
            }
            pd.DataFrame(summary_data).to_excel(writer, sheet_name="Summary", index=False)

        print(f"Exported to {filepath}")

    def get_summary(self) -> Dict[str, Any]:
        """Get summary statistics for the prospects."""
        if not self._prospects:
            return {"total": 0}

        df = self.to_dataframe()

        return {
            "total": len(df),
            "hot_count": len(df[df["Score"] >= 70]),
            "medium_count": len(df[(df["Score"] >= 50) & (df["Score"] < 70)]),
            "low_count": len(df[df["Score"] < 50]),
            "avg_score": round(df["Score"].mean(), 1),
            "with_phone": len(df[df["Phone"].notna() & (df["Phone"] != "")]),
            "by_state": df["State"].value_counts().to_dict() if "State" in df.columns else {},
        }
