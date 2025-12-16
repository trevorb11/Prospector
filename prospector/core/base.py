"""
Base classes for industry-specific prospect finders.

This module provides the abstract base class that all industry-specific
prospectors should inherit from, ensuring a consistent interface across
different data sources.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field, asdict
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

    # Primary contact information
    phone: Optional[str] = None
    email: Optional[str] = None
    website: Optional[str] = None

    # Additional phones/emails (from enrichment)
    secondary_phone: Optional[str] = None
    phone_type: Optional[str] = None  # mobile, landline, voip
    secondary_email: Optional[str] = None
    email_confidence: float = 0.0

    # LinkedIn data
    linkedin_url: Optional[str] = None
    linkedin_company_url: Optional[str] = None

    # Decision maker contact
    contact_name: Optional[str] = None
    contact_title: Optional[str] = None
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    contact_linkedin: Optional[str] = None

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
    employee_count_range: Optional[str] = None
    years_in_business: Optional[float] = None
    annual_revenue_range: Optional[str] = None

    # Industry-specific data
    industry_data: Dict[str, Any] = field(default_factory=dict)

    # Scoring
    prospect_score: int = 0
    score_breakdown: Dict[str, int] = field(default_factory=dict)

    # Loan triggers (enrichment data)
    loan_triggers: List[Dict[str, Any]] = field(default_factory=list)
    trigger_score_boost: int = 0
    trigger_priority: Optional[str] = None  # "high", "medium", "low"
    trigger_summary: Optional[str] = None

    # Funding signals (from funding_signals module)
    funding_signals: List[Dict[str, Any]] = field(default_factory=list)
    funding_likelihood: Optional[str] = None  # "high", "medium", "low"
    funding_signal_boost: int = 0
    recommended_products: List[str] = field(default_factory=list)
    recommended_timing: Optional[str] = None

    # Enrichment metadata
    enrichment_sources: List[str] = field(default_factory=list)
    enrichment_confidence: float = 0.0
    enriched_at: Optional[datetime] = None

    # Metadata
    source: Optional[str] = None
    retrieved_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for export."""
        base_dict = {
            "Score": self.prospect_score,
            "Trigger Priority": self.trigger_priority or "",
            "Funding Likelihood": self.funding_likelihood or "",
            "Trigger Summary": self.trigger_summary or "",
            "Company Name": self.company_name,
            "DBA Name": self.dba_name or "",
            "Phone": self.phone or "",
            "Secondary Phone": self.secondary_phone or "",
            "Email": self.email or "",
            "Secondary Email": self.secondary_email or "",
            "Website": self.website or "",
            "LinkedIn": self.linkedin_company_url or "",
            "Contact Name": self.contact_name or "",
            "Contact Title": self.contact_title or "",
            "Contact Email": self.contact_email or "",
            "Contact Phone": self.contact_phone or "",
            "Contact LinkedIn": self.contact_linkedin or "",
            "Address": self.address or "",
            "City": self.city or "",
            "State": self.state or "",
            "ZIP": self.zip_code or "",
            "Industry ID": self.industry_id or "",
            self.business_size_label or "Business Size": self.business_size_metric or "",
            "Employees": self.employee_count or "",
            "Employee Range": self.employee_count_range or "",
            "Years in Business": self.years_in_business or "",
            "Annual Revenue": self.annual_revenue_range or "",
            "Source": self.source or "",
        }

        # Add industry-specific fields
        for key, value in self.industry_data.items():
            base_dict[key] = value

        # Add loan trigger details as a formatted string
        if self.loan_triggers:
            trigger_names = [t.get("name", "") for t in self.loan_triggers[:3]]
            base_dict["Loan Triggers"] = "; ".join(trigger_names)
            base_dict["Trigger Count"] = len(self.loan_triggers)
            base_dict["Trigger Score Boost"] = self.trigger_score_boost
        else:
            base_dict["Loan Triggers"] = ""
            base_dict["Trigger Count"] = 0
            base_dict["Trigger Score Boost"] = 0

        # Add funding signals
        if self.funding_signals:
            signal_names = [s.get("signal_name", "") for s in self.funding_signals[:3]]
            base_dict["Funding Signals"] = "; ".join(signal_names)
            base_dict["Funding Signal Count"] = len(self.funding_signals)
            base_dict["Funding Signal Boost"] = self.funding_signal_boost
            base_dict["Recommended Products"] = ", ".join(self.recommended_products[:2]) if self.recommended_products else ""
            base_dict["Recommended Timing"] = self.recommended_timing or ""
        else:
            base_dict["Funding Signals"] = ""
            base_dict["Funding Signal Count"] = 0
            base_dict["Funding Signal Boost"] = 0
            base_dict["Recommended Products"] = ""
            base_dict["Recommended Timing"] = ""

        # Enrichment metadata
        base_dict["Enrichment Sources"] = ", ".join(self.enrichment_sources) if self.enrichment_sources else ""
        base_dict["Enrichment Confidence"] = self.enrichment_confidence

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
        Enrich a record with loan trigger detection.

        This method detects signals that indicate the prospect may be
        interested in financing, such as equipment lifecycle timing,
        business growth signals, and seasonality factors.

        Override this in subclasses to add industry-specific enrichment.

        Args:
            record: The prospect record to enrich

        Returns:
            Enriched prospect record with loan triggers
        """
        from .loan_triggers import get_trigger_detector, format_triggers_for_display

        # Get the appropriate detector for this industry
        detector = get_trigger_detector(self.get_industry_name())

        # Convert record to dict format for trigger detection
        record_dict = {
            "years_in_business": record.years_in_business,
            "industry_data": record.industry_data,
            "state": record.state,
            "business_size_metric": record.business_size_metric,
        }

        # Detect triggers
        triggers = detector.detect_triggers(record_dict)

        # Format and apply triggers to record
        trigger_data = format_triggers_for_display(triggers)

        record.loan_triggers = trigger_data["triggers"]
        record.trigger_score_boost = trigger_data["score_boost"]
        record.trigger_priority = trigger_data["priority"]
        record.trigger_summary = trigger_data["summary"]

        return record

    def run(self, score: bool = True, enrich: bool = True,
            enrich_contacts: bool = False, detect_funding_signals: bool = False,
            max_enrichment_workers: int = 5) -> List[ProspectRecord]:
        """
        Execute the full prospect finding pipeline.

        Args:
            score: Whether to score the prospects
            enrich: Whether to enrich with loan trigger detection (default: True)
            enrich_contacts: Whether to enrich with contact data (phone, email, LinkedIn)
            detect_funding_signals: Whether to detect funding signals (UCC, jobs, news)
            max_enrichment_workers: Max parallel workers for enrichment

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

        # Score prospects first (base scoring)
        if score:
            scoring_engine = ScoringEngine(self.get_scoring_rules())
            self._prospects = [scoring_engine.score(r) for r in self._prospects]

        # Enrich with loan trigger detection
        if enrich:
            print("\nEnriching prospects with loan trigger detection...")
            self._prospects = [self.enrich_record(r) for r in self._prospects]

            # Apply trigger score boost to final score
            for record in self._prospects:
                if record.trigger_score_boost > 0:
                    record.prospect_score += record.trigger_score_boost
                    record.score_breakdown["loan_triggers"] = record.trigger_score_boost

            # Count triggers by priority
            high_priority = sum(1 for r in self._prospects if r.trigger_priority == "high")
            medium_priority = sum(1 for r in self._prospects if r.trigger_priority == "medium")
            print(f"  High-priority triggers: {high_priority}")
            print(f"  Medium-priority triggers: {medium_priority}")

        # Contact enrichment (phone, email, LinkedIn)
        if enrich_contacts:
            print("\nEnriching contacts (phone, email, LinkedIn)...")
            self._prospects = self._enrich_contacts(
                self._prospects, max_workers=max_enrichment_workers
            )
            enriched_count = sum(1 for r in self._prospects if r.enrichment_confidence > 0)
            print(f"  Enriched {enriched_count} prospects with contact data")

        # Funding signal detection
        if detect_funding_signals:
            print("\nDetecting funding signals...")
            self._prospects = self._detect_funding_signals(
                self._prospects, max_workers=max_enrichment_workers
            )

            # Apply funding signal boost
            for record in self._prospects:
                if record.funding_signal_boost > 0:
                    record.prospect_score += record.funding_signal_boost
                    record.score_breakdown["funding_signals"] = record.funding_signal_boost

            high_funding = sum(1 for r in self._prospects if r.funding_likelihood == "high")
            med_funding = sum(1 for r in self._prospects if r.funding_likelihood == "medium")
            print(f"  High funding likelihood: {high_funding}")
            print(f"  Medium funding likelihood: {med_funding}")

        # Sort by score descending (after all boosts applied)
        if score:
            self._prospects.sort(key=lambda x: x.prospect_score, reverse=True)

        return self._prospects

    def _enrich_contacts(self, prospects: List[ProspectRecord],
                         max_workers: int = 5) -> List[ProspectRecord]:
        """
        Enrich prospects with contact data.

        Args:
            prospects: List of prospect records
            max_workers: Maximum parallel workers

        Returns:
            Enriched prospect records
        """
        try:
            from .contact_enrichment import ContactEnricher
            from datetime import datetime

            enricher = ContactEnricher(max_workers=max_workers)

            for i, record in enumerate(prospects):
                try:
                    contact_info = enricher.enrich(
                        company_name=record.company_name,
                        domain=record.website.replace("http://", "").replace("https://", "").split("/")[0] if record.website else None,
                        city=record.city,
                        state=record.state,
                        phone=record.phone
                    )

                    # Update record with enriched data
                    if contact_info.primary_email and not record.email:
                        record.email = contact_info.primary_email
                        record.email_confidence = contact_info.email_confidence
                    if contact_info.emails and len(contact_info.emails) > 1:
                        record.secondary_email = contact_info.emails[1].get("email")

                    if contact_info.primary_phone and not record.phone:
                        record.phone = contact_info.primary_phone
                        record.phone_type = contact_info.phone_type
                    if contact_info.phones and len(contact_info.phones) > 1:
                        record.secondary_phone = contact_info.phones[1].get("phone")

                    if contact_info.linkedin_company_url:
                        record.linkedin_company_url = contact_info.linkedin_company_url

                    if contact_info.company_website and not record.website:
                        record.website = contact_info.company_website

                    # Decision maker contact
                    if contact_info.decision_makers:
                        dm = contact_info.decision_makers[0]
                        record.contact_name = dm.get("name")
                        record.contact_title = dm.get("title")
                        record.contact_email = dm.get("email")
                        record.contact_phone = dm.get("phone")
                        record.contact_linkedin = dm.get("linkedin_url")

                    # Company data
                    if contact_info.employee_count_range:
                        record.employee_count_range = contact_info.employee_count_range
                    if contact_info.annual_revenue_range:
                        record.annual_revenue_range = contact_info.annual_revenue_range

                    record.enrichment_sources = contact_info.sources_used
                    record.enrichment_confidence = contact_info.confidence_score
                    record.enriched_at = datetime.now()

                except Exception as e:
                    print(f"Warning: Contact enrichment failed for {record.company_name}: {e}")

                # Progress indicator
                if (i + 1) % 10 == 0:
                    print(f"  Processed {i + 1}/{len(prospects)} contacts...")

        except ImportError:
            print("Warning: Contact enrichment module not available")

        return prospects

    def _detect_funding_signals(self, prospects: List[ProspectRecord],
                                max_workers: int = 5) -> List[ProspectRecord]:
        """
        Detect funding signals for prospects.

        Args:
            prospects: List of prospect records
            max_workers: Maximum parallel workers

        Returns:
            Prospects with funding signals detected
        """
        try:
            from .funding_signals import FundingSignalAnalyzer

            analyzer = FundingSignalAnalyzer(max_workers=max_workers)

            for i, record in enumerate(prospects):
                try:
                    report = analyzer.analyze(
                        company_name=record.company_name,
                        state=record.state,
                        industry=self.get_industry_name()
                    )

                    # Update record with funding signals
                    if report.signals:
                        record.funding_signals = [
                            {
                                "signal_name": s.signal_name,
                                "signal_type": s.signal_type,
                                "description": s.description,
                                "strength": s.strength
                            }
                            for s in report.signals
                        ]
                        record.funding_likelihood = report.funding_likelihood
                        record.funding_signal_boost = report.total_score_boost
                        record.recommended_products = report.recommended_products
                        record.recommended_timing = report.recommended_timing

                except Exception as e:
                    print(f"Warning: Funding signal detection failed for {record.company_name}: {e}")

                # Progress indicator
                if (i + 1) % 10 == 0:
                    print(f"  Analyzed {i + 1}/{len(prospects)} for funding signals...")

        except ImportError:
            print("Warning: Funding signals module not available")

        return prospects

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
        
        if df.empty or "Score" not in df.columns:
            return {"total": 0}

        return {
            "total": len(df),
            "hot_count": len(df[df["Score"] >= 70]),
            "medium_count": len(df[(df["Score"] >= 50) & (df["Score"] < 70)]),
            "low_count": len(df[df["Score"] < 50]),
            "avg_score": round(df["Score"].mean(), 1) if len(df) > 0 else 0,
            "with_phone": len(df[df["Phone"].notna() & (df["Phone"] != "")]) if "Phone" in df.columns else 0,
            "by_state": df["State"].value_counts().to_dict() if "State" in df.columns else {},
        }
