"""
MCA-Specific Scoring Engine
============================

Advanced scoring engine designed specifically for Merchant Cash Advance
lead prospecting. Replaces the generic scoring with industry-aware,
signal-rich scoring that factors in:

- Revenue estimation signals
- Time in business / maturity
- Industry-specific risk profiles
- Financing history (UCC cross-referencing)
- Seasonal cash flow patterns
- Contact quality signals
- Business entity structure
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Callable
from datetime import datetime, date
from enum import Enum
import math

from .scoring import ScoringEngine, ScoringRule, RuleType


class MCAIndustryProfile(Enum):
    """Industry verticals with distinct MCA profiles."""
    TRUCKING = "trucking"
    HEALTHCARE = "healthcare"
    CONSTRUCTION = "construction"
    RESTAURANT = "restaurant"
    AVIATION = "aviation"
    RETAIL = "retail"
    GENERAL = "general"


@dataclass
class SeasonalPattern:
    """Monthly cash flow pattern for an industry (1.0 = average, >1.0 = peak, <1.0 = slow)."""
    jan: float = 1.0
    feb: float = 1.0
    mar: float = 1.0
    apr: float = 1.0
    may: float = 1.0
    jun: float = 1.0
    jul: float = 1.0
    aug: float = 1.0
    sep: float = 1.0
    oct: float = 1.0
    nov: float = 1.0
    dec: float = 1.0

    def get_current_factor(self) -> float:
        """Get the seasonal factor for the current month."""
        month = datetime.now().month
        factors = [self.jan, self.feb, self.mar, self.apr, self.may, self.jun,
                   self.jul, self.aug, self.sep, self.oct, self.nov, self.dec]
        return factors[month - 1]

    def is_pre_slow_season(self) -> bool:
        """Check if we're 1-2 months before a slow period (businesses need cash reserves)."""
        month = datetime.now().month
        factors = [self.jan, self.feb, self.mar, self.apr, self.may, self.jun,
                   self.jul, self.aug, self.sep, self.oct, self.nov, self.dec]
        next_month = factors[month % 12]
        month_after = factors[(month + 1) % 12]
        return next_month < 0.85 or month_after < 0.85

    def is_pre_peak_season(self) -> bool:
        """Check if we're 1-2 months before a peak (businesses need working capital to ramp up)."""
        month = datetime.now().month
        factors = [self.jan, self.feb, self.mar, self.apr, self.may, self.jun,
                   self.jul, self.aug, self.sep, self.oct, self.nov, self.dec]
        next_month = factors[month % 12]
        month_after = factors[(month + 1) % 12]
        return next_month > 1.15 or month_after > 1.15


# Industry seasonal patterns based on typical cash flow cycles
SEASONAL_PATTERNS = {
    MCAIndustryProfile.TRUCKING: SeasonalPattern(
        jan=0.85, feb=0.88, mar=1.0, apr=1.05, may=1.10, jun=1.12,
        jul=1.08, aug=1.10, sep=1.15, oct=1.12, nov=1.05, dec=0.80
    ),
    MCAIndustryProfile.HEALTHCARE: SeasonalPattern(
        jan=1.15, feb=1.05, mar=1.0, apr=0.95, may=0.95, jun=0.90,
        jul=0.88, aug=0.90, sep=1.0, oct=1.05, nov=1.05, dec=0.85
    ),
    MCAIndustryProfile.CONSTRUCTION: SeasonalPattern(
        jan=0.65, feb=0.70, mar=0.90, apr=1.10, may=1.20, jun=1.25,
        jul=1.20, aug=1.18, sep=1.15, oct=1.05, nov=0.85, dec=0.65
    ),
    MCAIndustryProfile.RESTAURANT: SeasonalPattern(
        jan=0.75, feb=0.80, mar=0.90, apr=0.95, may=1.05, jun=1.15,
        jul=1.15, aug=1.10, sep=0.95, oct=1.0, nov=1.10, dec=1.20
    ),
    MCAIndustryProfile.AVIATION: SeasonalPattern(
        jan=0.85, feb=0.90, mar=1.0, apr=1.05, may=1.10, jun=1.15,
        jul=1.15, aug=1.10, sep=1.0, oct=0.95, nov=0.90, dec=0.85
    ),
    MCAIndustryProfile.RETAIL: SeasonalPattern(
        jan=0.70, feb=0.75, mar=0.85, apr=0.90, may=0.95, jun=1.0,
        jul=1.0, aug=1.05, sep=1.05, oct=1.10, nov=1.25, dec=1.35
    ),
    MCAIndustryProfile.GENERAL: SeasonalPattern(),
}


@dataclass
class IndustryRiskProfile:
    """MCA risk/opportunity profile for a specific industry."""
    industry: MCAIndustryProfile
    # Revenue estimation parameters
    avg_revenue_per_unit: float  # Average annual revenue per business_size_metric unit
    revenue_unit_label: str  # What the unit represents (e.g., "truck", "provider", "aircraft")
    # MCA deal parameters
    ideal_size_min: int  # Ideal business size minimum
    ideal_size_max: int  # Ideal business size maximum
    typical_advance_range: tuple  # (min_advance, max_advance) in dollars
    # Risk factors
    default_risk_tier: str  # "low", "medium", "high"
    avg_time_in_business_years: float  # Average for the industry
    # Scoring weights (sum should be ~1.0 for relative weighting)
    weight_size: float = 0.25
    weight_revenue: float = 0.20
    weight_time_in_biz: float = 0.15
    weight_contact_quality: float = 0.15
    weight_financing_history: float = 0.15
    weight_seasonality: float = 0.10


# Industry risk profiles tuned for MCA prospecting
INDUSTRY_PROFILES = {
    MCAIndustryProfile.TRUCKING: IndustryRiskProfile(
        industry=MCAIndustryProfile.TRUCKING,
        avg_revenue_per_unit=150000,  # ~$150K revenue per truck
        revenue_unit_label="truck",
        ideal_size_min=3,
        ideal_size_max=25,
        typical_advance_range=(25000, 250000),
        default_risk_tier="medium",
        avg_time_in_business_years=8,
        weight_size=0.25,
        weight_revenue=0.20,
        weight_time_in_biz=0.15,
        weight_contact_quality=0.15,
        weight_financing_history=0.15,
        weight_seasonality=0.10,
    ),
    MCAIndustryProfile.HEALTHCARE: IndustryRiskProfile(
        industry=MCAIndustryProfile.HEALTHCARE,
        avg_revenue_per_unit=500000,  # ~$500K per provider/location
        revenue_unit_label="provider",
        ideal_size_min=1,
        ideal_size_max=10,
        typical_advance_range=(50000, 500000),
        default_risk_tier="low",
        avg_time_in_business_years=12,
        weight_size=0.15,
        weight_revenue=0.25,
        weight_time_in_biz=0.20,
        weight_contact_quality=0.15,
        weight_financing_history=0.10,
        weight_seasonality=0.15,
    ),
    MCAIndustryProfile.CONSTRUCTION: IndustryRiskProfile(
        industry=MCAIndustryProfile.CONSTRUCTION,
        avg_revenue_per_unit=200000,  # ~$200K per crew/unit
        revenue_unit_label="crew",
        ideal_size_min=5,
        ideal_size_max=50,
        typical_advance_range=(25000, 300000),
        default_risk_tier="high",
        avg_time_in_business_years=6,
        weight_size=0.20,
        weight_revenue=0.20,
        weight_time_in_biz=0.20,
        weight_contact_quality=0.10,
        weight_financing_history=0.15,
        weight_seasonality=0.15,
    ),
    MCAIndustryProfile.RESTAURANT: IndustryRiskProfile(
        industry=MCAIndustryProfile.RESTAURANT,
        avg_revenue_per_unit=800000,  # ~$800K per location
        revenue_unit_label="location",
        ideal_size_min=1,
        ideal_size_max=5,
        typical_advance_range=(15000, 150000),
        default_risk_tier="high",
        avg_time_in_business_years=5,
        weight_size=0.15,
        weight_revenue=0.20,
        weight_time_in_biz=0.20,
        weight_contact_quality=0.15,
        weight_financing_history=0.15,
        weight_seasonality=0.15,
    ),
    MCAIndustryProfile.AVIATION: IndustryRiskProfile(
        industry=MCAIndustryProfile.AVIATION,
        avg_revenue_per_unit=300000,  # ~$300K per aircraft
        revenue_unit_label="aircraft",
        ideal_size_min=2,
        ideal_size_max=20,
        typical_advance_range=(50000, 500000),
        default_risk_tier="low",
        avg_time_in_business_years=10,
        weight_size=0.25,
        weight_revenue=0.25,
        weight_time_in_biz=0.15,
        weight_contact_quality=0.10,
        weight_financing_history=0.15,
        weight_seasonality=0.10,
    ),
    MCAIndustryProfile.GENERAL: IndustryRiskProfile(
        industry=MCAIndustryProfile.GENERAL,
        avg_revenue_per_unit=100000,
        revenue_unit_label="unit",
        ideal_size_min=2,
        ideal_size_max=30,
        typical_advance_range=(15000, 200000),
        default_risk_tier="medium",
        avg_time_in_business_years=7,
    ),
}


class MCAScorer:
    """
    MCA-specific scoring engine that evaluates prospects across multiple
    dimensions with industry-aware weighting.

    Scoring dimensions (each scored 0-100, then weighted):
    1. Business Size Fit - Is this the right size for MCA?
    2. Revenue Estimation - Estimated revenue from proxy signals
    3. Time in Business - Maturity and stability
    4. Contact Quality - Can we actually reach them?
    5. Financing History - Have they used financing before?
    6. Seasonal Timing - Is this a good time to reach out?

    Final score = weighted sum of dimensions, scaled 0-100.
    """

    def __init__(
        self,
        industry: MCAIndustryProfile = MCAIndustryProfile.GENERAL,
        ucc_matches: Optional[Dict[str, List[Dict]]] = None,
        custom_weights: Optional[Dict[str, float]] = None,
    ):
        self.industry = industry
        self.profile = INDUSTRY_PROFILES.get(industry, INDUSTRY_PROFILES[MCAIndustryProfile.GENERAL])
        self.seasonal = SEASONAL_PATTERNS.get(industry, SEASONAL_PATTERNS[MCAIndustryProfile.GENERAL])
        self.ucc_matches = ucc_matches or {}
        if custom_weights:
            if "size" in custom_weights:
                self.profile.weight_size = custom_weights["size"]
            if "revenue" in custom_weights:
                self.profile.weight_revenue = custom_weights["revenue"]
            if "time_in_biz" in custom_weights:
                self.profile.weight_time_in_biz = custom_weights["time_in_biz"]
            if "contact_quality" in custom_weights:
                self.profile.weight_contact_quality = custom_weights["contact_quality"]
            if "financing_history" in custom_weights:
                self.profile.weight_financing_history = custom_weights["financing_history"]
            if "seasonality" in custom_weights:
                self.profile.weight_seasonality = custom_weights["seasonality"]

    def score(self, record: Any) -> Any:
        """
        Score a prospect record using MCA-specific multi-dimensional analysis.

        Args:
            record: ProspectRecord to score

        Returns:
            The record with prospect_score and score_breakdown populated
        """
        breakdown = {}

        # Dimension 1: Business Size Fit
        size_score = self._score_business_size(record)
        breakdown["size_fit"] = size_score

        # Dimension 2: Revenue Estimation
        revenue_score = self._score_revenue_signals(record)
        breakdown["revenue_signal"] = revenue_score

        # Dimension 3: Time in Business
        tib_score = self._score_time_in_business(record)
        breakdown["time_in_business"] = tib_score

        # Dimension 4: Contact Quality
        contact_score = self._score_contact_quality(record)
        breakdown["contact_quality"] = contact_score

        # Dimension 5: Financing History
        financing_score = self._score_financing_history(record)
        breakdown["financing_history"] = financing_score

        # Dimension 6: Seasonal Timing
        seasonal_score = self._score_seasonal_timing(record)
        breakdown["seasonal_timing"] = seasonal_score

        # Industry-specific bonus signals
        industry_bonus = self._score_industry_specific(record)
        breakdown["industry_bonus"] = industry_bonus

        # Calculate weighted final score
        p = self.profile
        weighted_score = (
            size_score * p.weight_size +
            revenue_score * p.weight_revenue +
            tib_score * p.weight_time_in_biz +
            contact_score * p.weight_contact_quality +
            financing_score * p.weight_financing_history +
            seasonal_score * p.weight_seasonality
        )

        # Add industry bonus (up to 10 extra points)
        weighted_score = min(100, weighted_score + (industry_bonus * 0.10))

        # Store estimated revenue for output
        estimated_revenue = self._estimate_revenue(record)
        breakdown["estimated_annual_revenue"] = estimated_revenue
        breakdown["revenue_range"] = self._revenue_range_label(estimated_revenue)

        # Best time to contact recommendation
        breakdown["seasonal_recommendation"] = self._seasonal_recommendation()

        record.prospect_score = round(min(100, max(0, weighted_score)))

        # Risk tier assessment (after score is set)
        breakdown["risk_tier"] = self._assess_risk_tier(record, breakdown)

        record.score_breakdown = breakdown

        # Store enrichment data in industry_data
        record.industry_data["MCA Score"] = record.prospect_score
        record.industry_data["Est. Annual Revenue"] = breakdown["revenue_range"]
        record.industry_data["Risk Tier"] = breakdown["risk_tier"]
        record.industry_data["Financing History"] = "Yes" if financing_score > 50 else "No"
        record.industry_data["Seasonal Timing"] = breakdown["seasonal_recommendation"]

        return record

    def score_batch(self, records: List[Any]) -> List[Any]:
        """Score a batch of prospect records."""
        scored = [self.score(r) for r in records]
        scored.sort(key=lambda x: x.prospect_score, reverse=True)
        return scored

    def _score_business_size(self, record: Any) -> float:
        """Score based on how well the business size fits the MCA sweet spot."""
        size = record.business_size_metric
        if size is None or size == 0:
            # No size data - use employee count as fallback
            if record.employee_count and record.employee_count > 0:
                size = record.employee_count
            else:
                return 30  # Unknown size = neutral-low score

        size = float(size)
        ideal_min = self.profile.ideal_size_min
        ideal_max = self.profile.ideal_size_max

        if ideal_min <= size <= ideal_max:
            # In the sweet spot - score based on position within range
            midpoint = (ideal_min + ideal_max) / 2
            distance_from_mid = abs(size - midpoint) / (ideal_max - ideal_min)
            return 85 + (15 * (1 - distance_from_mid))  # 85-100
        elif size < ideal_min:
            # Too small - might not qualify
            if size <= 0:
                return 10
            ratio = size / ideal_min
            return max(15, ratio * 60)  # 15-60
        else:
            # Too large - probably has bank relationships
            overshoot = size / ideal_max
            if overshoot > 5:
                return 10  # Way too large
            elif overshoot > 3:
                return 25
            elif overshoot > 2:
                return 40
            else:
                return 55  # Just above sweet spot, still viable

    def _score_revenue_signals(self, record: Any) -> float:
        """Score based on estimated revenue proxy signals."""
        estimated_rev = self._estimate_revenue(record)

        if estimated_rev <= 0:
            return 25  # No data

        min_advance, max_advance = self.profile.typical_advance_range

        # MCA typically requires 4-6x monthly revenue coverage
        # So ideal annual revenue = advance_amount * 12 / 4 to advance_amount * 12 / 6
        ideal_rev_min = min_advance * 3  # Conservative: can support the minimum advance
        ideal_rev_max = max_advance * 8  # Upper bound: very healthy revenue

        if ideal_rev_min <= estimated_rev <= ideal_rev_max:
            return 90  # Revenue supports MCA comfortably
        elif estimated_rev < ideal_rev_min:
            ratio = estimated_rev / ideal_rev_min
            return max(20, ratio * 70)
        else:
            # Very high revenue - they probably use bank lines
            return 60  # Still a prospect but may not need MCA

    def _estimate_revenue(self, record: Any) -> float:
        """Estimate annual revenue from available proxy signals."""
        size = record.business_size_metric
        employees = record.employee_count

        if size and float(size) > 0:
            return float(size) * self.profile.avg_revenue_per_unit

        if employees and employees > 0:
            # General rule: ~$100K-200K revenue per employee for SMBs
            return employees * 120000

        return 0

    def _revenue_range_label(self, estimated_rev: float) -> str:
        """Convert estimated revenue to a human-readable range."""
        if estimated_rev <= 0:
            return "Unknown"
        elif estimated_rev < 250000:
            return "Under $250K"
        elif estimated_rev < 500000:
            return "$250K-$500K"
        elif estimated_rev < 1000000:
            return "$500K-$1M"
        elif estimated_rev < 2500000:
            return "$1M-$2.5M"
        elif estimated_rev < 5000000:
            return "$2.5M-$5M"
        elif estimated_rev < 10000000:
            return "$5M-$10M"
        else:
            return "$10M+"

    def _score_time_in_business(self, record: Any) -> float:
        """Score based on time in business. MCA typically requires 6mo+ minimum."""
        years = record.years_in_business

        if years is None:
            # Try to infer from industry_data
            years = self._infer_years_in_business(record)

        if years is None:
            return 35  # Unknown

        if years < 0.5:
            return 5  # Too new - most MCA requires 6 months minimum
        elif years < 1:
            return 30  # Borderline
        elif years < 2:
            return 55  # Qualifies but higher risk
        elif years < 5:
            return 80  # Solid track record
        elif years < 15:
            return 95  # Established business, great prospect
        else:
            return 85  # Very established - may have bank relationships

    def _infer_years_in_business(self, record: Any) -> Optional[float]:
        """Try to infer time in business from industry-specific data."""
        industry_data = record.industry_data or {}

        # Trucking: use MCS-150 date
        mcs_date = industry_data.get("Last Updated")
        if mcs_date:
            try:
                if len(mcs_date) >= 10:
                    dt = datetime.strptime(mcs_date[:10], "%Y-%m-%d")
                    # MCS-150 must be filed every 2 years, so last update gives a lower bound
                    return max(2, (datetime.now() - dt).days / 365 + 2)
            except (ValueError, TypeError):
                pass

        # Healthcare: use enumeration date
        enum_date = industry_data.get("Enumeration Date")
        if enum_date:
            try:
                year = int(enum_date.split("-")[0])
                return datetime.now().year - year
            except (ValueError, IndexError, TypeError):
                pass

        # Construction: use license issue date
        license_date = industry_data.get("License Date") or industry_data.get("Issue Date")
        if license_date:
            try:
                if len(license_date) >= 4:
                    year = int(license_date[:4])
                    return datetime.now().year - year
            except (ValueError, TypeError):
                pass

        # UCC: use earliest filing date
        file_date = industry_data.get("File Date")
        if file_date:
            try:
                if len(file_date) >= 4:
                    year = int(file_date[:4])
                    return max(1, datetime.now().year - year)
            except (ValueError, TypeError):
                pass

        return None

    def _score_contact_quality(self, record: Any) -> float:
        """Score based on how reachable this prospect is."""
        score = 0

        # Phone number (most valuable for MCA sales)
        if record.phone and str(record.phone).strip():
            phone = str(record.phone).strip()
            digits = ''.join(c for c in phone if c.isdigit())
            if len(digits) >= 10:
                score += 45  # Valid phone number
            else:
                score += 15  # Partial phone

        # Email
        if record.email and str(record.email).strip() and "@" in str(record.email):
            score += 25

        # Website
        if record.website and str(record.website).strip():
            score += 10

        # Physical address completeness
        if record.address and record.city and record.state and record.zip_code:
            score += 15  # Full address = can send direct mail
        elif record.address and record.state:
            score += 5

        # DBA name (indicates active/public-facing business)
        if record.dba_name and str(record.dba_name).strip():
            score += 5

        return min(100, score)

    def _score_financing_history(self, record: Any) -> float:
        """
        Score based on known financing history.
        Uses UCC cross-reference data when available.
        """
        # Check if this business has UCC filings
        company_name = (record.company_name or "").upper().strip()
        industry_data = record.industry_data or {}

        # Direct UCC match from cross-reference
        if company_name in self.ucc_matches:
            filings = self.ucc_matches[company_name]
            num_filings = len(filings)

            if num_filings >= 5:
                return 95  # Very active borrower
            elif num_filings >= 3:
                return 85  # Regular borrower
            elif num_filings >= 1:
                return 75  # Has used financing

        # Check if the prospect itself is from UCC data
        source = (record.source or "").upper()
        if "UCC" in source:
            filing_type = industry_data.get("Filing Type", "")
            if "FIN STMT" in filing_type or "OFS" in filing_type:
                return 80  # Active financing statement
            return 65  # Some kind of UCC filing

        # Check for industry-specific financing indicators
        if self.industry == MCAIndustryProfile.TRUCKING:
            # Interstate carriers often need more financing
            op_type = industry_data.get("Operation Type", "")
            if op_type == "A":  # Interstate
                return 40  # Moderate likelihood of financing needs
            return 30

        if self.industry == MCAIndustryProfile.AVIATION:
            # Turbine aircraft = high-value financing
            engine_types = industry_data.get("Engine Types", "")
            if "Turbo" in engine_types:
                return 50

        # Default: no financing history known
        return 20

    def _score_seasonal_timing(self, record: Any) -> float:
        """Score based on whether this is a good time to contact this industry."""
        if self.seasonal.is_pre_slow_season():
            # Before slow season = businesses looking to shore up cash
            return 90
        elif self.seasonal.is_pre_peak_season():
            # Before peak season = businesses need working capital to ramp up
            return 85
        else:
            current_factor = self.seasonal.get_current_factor()
            if current_factor < 0.85:
                # During slow season - business may be cash-strapped RIGHT NOW
                return 80
            elif current_factor > 1.1:
                # Peak season - busy, hard to reach, but cash is flowing
                return 50
            else:
                # Normal season
                return 65

    def _seasonal_recommendation(self) -> str:
        """Get a human-readable seasonal recommendation."""
        if self.seasonal.is_pre_slow_season():
            return "HIGH - Pre-slow season (businesses building cash reserves)"
        elif self.seasonal.is_pre_peak_season():
            return "HIGH - Pre-peak season (businesses ramping up)"
        else:
            current_factor = self.seasonal.get_current_factor()
            if current_factor < 0.85:
                return "GOOD - Slow season (businesses may need cash)"
            elif current_factor > 1.1:
                return "MODERATE - Peak season (busy but flush)"
            else:
                return "NORMAL - Standard season"

    def _score_industry_specific(self, record: Any) -> float:
        """Apply industry-specific bonus scoring."""
        industry_data = record.industry_data or {}
        bonus = 0

        if self.industry == MCAIndustryProfile.TRUCKING:
            bonus += self._trucking_bonus(record, industry_data)
        elif self.industry == MCAIndustryProfile.HEALTHCARE:
            bonus += self._healthcare_bonus(record, industry_data)
        elif self.industry == MCAIndustryProfile.CONSTRUCTION:
            bonus += self._construction_bonus(record, industry_data)
        elif self.industry == MCAIndustryProfile.RESTAURANT:
            bonus += self._restaurant_bonus(record, industry_data)
        elif self.industry == MCAIndustryProfile.AVIATION:
            bonus += self._aviation_bonus(record, industry_data)

        return min(100, bonus)

    def _trucking_bonus(self, record: Any, data: Dict) -> float:
        """Trucking-specific bonus signals."""
        bonus = 0

        # Active status
        status = data.get("Status", "")
        if status == "ACTIVE":
            bonus += 20

        # Interstate carrier (broader operations = more revenue)
        op_type = data.get("Operation Type", "")
        if op_type == "A":
            bonus += 15

        # Has drivers (active operations)
        drivers = data.get("Drivers")
        if drivers and int(drivers or 0) > 0:
            bonus += 15

        # Recent MCS-150 update (actively maintaining compliance)
        last_updated = data.get("Last Updated", "")
        if last_updated:
            try:
                if len(last_updated) >= 4:
                    year = int(last_updated[:4])
                    if datetime.now().year - year <= 2:
                        bonus += 20
            except (ValueError, TypeError):
                pass

        # DOT number present (verified business)
        if data.get("DOT Number"):
            bonus += 10

        return bonus

    def _healthcare_bonus(self, record: Any, data: Dict) -> float:
        """Healthcare-specific bonus signals."""
        bonus = 0

        # Organization vs Individual (organizations = better MCA candidates)
        entity_type = data.get("Entity Type", "")
        if entity_type == "Organization":
            bonus += 25

        # High-value specialties (expensive equipment = financing needs)
        specialty = data.get("Primary Specialty", "").lower()
        high_value_specialties = ["dental", "radiol", "surg", "ophthal", "orthop", "cardio"]
        for hv in high_value_specialties:
            if hv in specialty:
                bonus += 25
                break

        medium_value_specialties = ["physical therap", "chiropr", "clinic", "urgent care"]
        for mv in medium_value_specialties:
            if mv in specialty:
                bonus += 15
                break

        # Multiple specialties (larger practice)
        all_specs = data.get("All Specialties", "")
        if all_specs and ";" in all_specs:
            bonus += 10

        # Established practice
        enum_date = data.get("Enumeration Date", "")
        if enum_date:
            try:
                year = int(enum_date.split("-")[0])
                years_active = datetime.now().year - year
                if 3 <= years_active <= 20:
                    bonus += 15
            except (ValueError, IndexError):
                pass

        return bonus

    def _construction_bonus(self, record: Any, data: Dict) -> float:
        """Construction-specific bonus signals."""
        bonus = 0

        # General contractor (larger operations)
        license_type = data.get("License Type", "").lower()
        if "general" in license_type:
            bonus += 25
        elif any(t in license_type for t in ["electrical", "hvac", "plumbing", "mechanical"]):
            bonus += 20
        elif any(t in license_type for t in ["heavy civil", "highway", "pipeline"]):
            bonus += 30  # Heavy civil = big equipment needs

        # Active license
        status = data.get("License Status", data.get("Status", "")).lower()
        if "active" in status:
            bonus += 15

        # Bonding capacity (if available - indicates established business)
        bond = data.get("Bond Amount", data.get("Bonding", 0))
        if bond:
            try:
                bond_val = float(str(bond).replace("$", "").replace(",", ""))
                if bond_val >= 100000:
                    bonus += 20
                elif bond_val >= 25000:
                    bonus += 10
            except (ValueError, TypeError):
                pass

        return bonus

    def _restaurant_bonus(self, record: Any, data: Dict) -> float:
        """Restaurant-specific bonus signals."""
        bonus = 0

        # Inspection grade (A = well-run, likely to be approved for MCA)
        grade = data.get("Grade", data.get("grade", ""))
        if grade == "A":
            bonus += 25
        elif grade == "B":
            bonus += 15

        # Cuisine type (some are higher revenue)
        cuisine = data.get("Cuisine", data.get("cuisine", "")).lower()
        high_rev_cuisines = ["japanese", "italian", "french", "steakhouse", "seafood", "korean"]
        if any(c in cuisine for c in high_rev_cuisines):
            bonus += 15

        # Borough/location (Manhattan = higher revenue)
        boro = data.get("Borough", data.get("boro", "")).upper()
        if "MANHATTAN" in boro:
            bonus += 15
        elif "BROOKLYN" in boro:
            bonus += 10

        return bonus

    def _aviation_bonus(self, record: Any, data: Dict) -> float:
        """Aviation-specific bonus signals."""
        bonus = 0

        # Turbine aircraft (very high value)
        engine_types = data.get("Engine Types", "")
        if "Turbo-fan" in engine_types or "Turbo-jet" in engine_types:
            bonus += 30
        elif "Turbo-prop" in engine_types or "Turbo-shaft" in engine_types:
            bonus += 20

        # Business entity type
        owner_type = data.get("Owner Type", "")
        if owner_type in ("Corporation", "LLC"):
            bonus += 20

        # Recent aircraft acquisition
        newest_year = data.get("Newest Aircraft Year", "")
        if newest_year:
            try:
                year = int(newest_year)
                if datetime.now().year - year <= 3:
                    bonus += 20  # Recently acquired = active buyer
                elif datetime.now().year - year <= 7:
                    bonus += 10
            except (ValueError, TypeError):
                pass

        # Fleet size bonus
        aircraft_count = data.get("Aircraft Count", 0)
        if aircraft_count and int(aircraft_count) >= 3:
            bonus += 15

        return bonus

    def _assess_risk_tier(self, record: Any, breakdown: Dict) -> str:
        """Assess overall MCA risk tier for this prospect."""
        score = record.prospect_score
        tib = breakdown.get("time_in_business", 0)
        revenue = breakdown.get("estimated_annual_revenue", 0)

        if score >= 80 and tib >= 70 and revenue > 0:
            return "A - Prime"
        elif score >= 65 and tib >= 50:
            return "B - Standard"
        elif score >= 50:
            return "C - Moderate Risk"
        elif score >= 35:
            return "D - Higher Risk"
        else:
            return "E - Not Recommended"

    def get_scoring_summary(self) -> Dict[str, Any]:
        """Get a summary of the scoring configuration for this industry."""
        return {
            "industry": self.industry.value,
            "ideal_business_size": f"{self.profile.ideal_size_min}-{self.profile.ideal_size_max} {self.profile.revenue_unit_label}s",
            "avg_revenue_per_unit": f"${self.profile.avg_revenue_per_unit:,.0f}",
            "typical_advance_range": f"${self.profile.typical_advance_range[0]:,.0f}-${self.profile.typical_advance_range[1]:,.0f}",
            "default_risk_tier": self.profile.default_risk_tier,
            "seasonal_recommendation": self._seasonal_recommendation(),
            "weights": {
                "size": self.profile.weight_size,
                "revenue": self.profile.weight_revenue,
                "time_in_business": self.profile.weight_time_in_biz,
                "contact_quality": self.profile.weight_contact_quality,
                "financing_history": self.profile.weight_financing_history,
                "seasonality": self.profile.weight_seasonality,
            },
        }


def detect_industry_profile(source_name: str) -> MCAIndustryProfile:
    """Auto-detect the industry profile from a prospect's source name."""
    source = (source_name or "").lower()

    if "truck" in source or "fmcsa" in source or "dot" in source:
        return MCAIndustryProfile.TRUCKING
    elif "health" in source or "npi" in source or "medical" in source:
        return MCAIndustryProfile.HEALTHCARE
    elif "construct" in source or "contractor" in source or "cslb" in source or "license" in source:
        return MCAIndustryProfile.CONSTRUCTION
    elif "restaurant" in source or "food" in source or "dohmh" in source:
        return MCAIndustryProfile.RESTAURANT
    elif "aviat" in source or "faa" in source or "aircraft" in source:
        return MCAIndustryProfile.AVIATION
    else:
        return MCAIndustryProfile.GENERAL
