"""
Loan Trigger Detection and Enrichment
======================================

This module provides functionality to detect signals that indicate a business
may be interested in financing. These "loan triggers" help prioritize prospects
who are most likely to convert.

Loan triggers include:
- Equipment lifecycle (replacement timing)
- Business growth signals (expansion, hiring)
- Seasonality factors (pre-season equipment needs)
- Recent changes (new ownership, restructuring)
- Regulatory compliance needs
- Fleet/equipment age
"""

import re
import requests
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from enum import Enum


class TriggerType(Enum):
    """Categories of loan triggers."""
    EQUIPMENT_LIFECYCLE = "equipment_lifecycle"
    GROWTH_SIGNAL = "growth_signal"
    SEASONALITY = "seasonality"
    NEW_BUSINESS = "new_business"
    EXPANSION = "expansion"
    REGULATORY = "regulatory"
    FLEET_AGE = "fleet_age"
    RECENT_ACTIVITY = "recent_activity"
    HIGH_VALUE_SPECIALTY = "high_value_specialty"


class TriggerPriority(Enum):
    """Priority levels for triggers."""
    HIGH = "high"      # Strong buying signal, reach out immediately
    MEDIUM = "medium"  # Good timing, include in outreach
    LOW = "low"        # Potential opportunity, monitor


@dataclass
class LoanTrigger:
    """Represents a detected loan trigger."""
    trigger_type: TriggerType
    priority: TriggerPriority
    name: str
    description: str
    score_boost: int = 0
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.trigger_type.value,
            "priority": self.priority.value,
            "name": self.name,
            "description": self.description,
            "score_boost": self.score_boost,
            "details": self.details,
        }


class LoanTriggerDetector:
    """
    Base class for detecting loan triggers across industries.

    Provides common trigger detection logic that can be extended
    by industry-specific implementations.
    """

    def __init__(self):
        self.current_month = datetime.now().month
        self.current_year = datetime.now().year

    def detect_triggers(self, record: Dict[str, Any]) -> List[LoanTrigger]:
        """
        Detect all applicable loan triggers for a prospect record.

        Args:
            record: Prospect data dictionary

        Returns:
            List of detected LoanTrigger objects
        """
        triggers = []

        # Check common triggers
        triggers.extend(self._check_business_age_triggers(record))
        triggers.extend(self._check_seasonality_triggers(record))

        return triggers

    def _check_business_age_triggers(self, record: Dict[str, Any]) -> List[LoanTrigger]:
        """Check for triggers based on business age."""
        triggers = []
        years = record.get("years_in_business")

        if years is not None:
            # New business (0-2 years) - needs initial equipment
            if 0 <= years <= 2:
                triggers.append(LoanTrigger(
                    trigger_type=TriggerType.NEW_BUSINESS,
                    priority=TriggerPriority.HIGH,
                    name="New Business",
                    description=f"Business is {years} year(s) old - likely needs equipment financing for startup/growth",
                    score_boost=15,
                    details={"years_in_business": years}
                ))

            # Equipment replacement cycle (5-7 years)
            elif 5 <= years <= 7:
                triggers.append(LoanTrigger(
                    trigger_type=TriggerType.EQUIPMENT_LIFECYCLE,
                    priority=TriggerPriority.MEDIUM,
                    name="Equipment Refresh Cycle",
                    description=f"Business is {years} years old - may be in equipment replacement cycle",
                    score_boost=10,
                    details={"years_in_business": years}
                ))

            # Second equipment cycle (10-12 years)
            elif 10 <= years <= 12:
                triggers.append(LoanTrigger(
                    trigger_type=TriggerType.EQUIPMENT_LIFECYCLE,
                    priority=TriggerPriority.MEDIUM,
                    name="Second Equipment Cycle",
                    description=f"Established business ({years} years) - likely due for major equipment refresh",
                    score_boost=10,
                    details={"years_in_business": years}
                ))

        return triggers

    def _check_seasonality_triggers(self, record: Dict[str, Any]) -> List[LoanTrigger]:
        """Check for seasonal financing triggers."""
        triggers = []
        industry = record.get("industry", "").lower()

        # Q4 (Oct-Dec) - Year-end tax planning, Section 179 deductions
        if self.current_month in [10, 11, 12]:
            triggers.append(LoanTrigger(
                trigger_type=TriggerType.SEASONALITY,
                priority=TriggerPriority.HIGH,
                name="Year-End Tax Planning",
                description="Q4 - businesses may want to purchase equipment for Section 179 tax deductions",
                score_boost=15,
                details={"season": "Q4", "reason": "tax_planning"}
            ))

        # Q1 (Jan-Mar) - New year budget, fresh capital
        elif self.current_month in [1, 2, 3]:
            triggers.append(LoanTrigger(
                trigger_type=TriggerType.SEASONALITY,
                priority=TriggerPriority.MEDIUM,
                name="New Year Budget Cycle",
                description="Q1 - new budgets allocated, good time for equipment discussions",
                score_boost=10,
                details={"season": "Q1", "reason": "new_budget"}
            ))

        return triggers

    def calculate_total_score_boost(self, triggers: List[LoanTrigger]) -> int:
        """Calculate total score boost from all triggers."""
        return sum(t.score_boost for t in triggers)

    def get_highest_priority(self, triggers: List[LoanTrigger]) -> Optional[TriggerPriority]:
        """Get the highest priority level from triggers."""
        if not triggers:
            return None

        priority_order = {
            TriggerPriority.HIGH: 3,
            TriggerPriority.MEDIUM: 2,
            TriggerPriority.LOW: 1,
        }

        return max(triggers, key=lambda t: priority_order[t.priority]).priority


class HealthcareTriggerDetector(LoanTriggerDetector):
    """
    Healthcare-specific loan trigger detection.

    Detects triggers like:
    - Equipment lifecycle (imaging, dental chairs, etc.)
    - Practice expansion signals
    - New practice startup
    - Technology upgrade cycles
    """

    # Equipment replacement cycles by specialty (years)
    EQUIPMENT_CYCLES = {
        "dental": 7,      # Dental chairs, X-ray, CAD/CAM
        "radiology": 5,   # CT, MRI, X-ray equipment
        "imaging": 5,     # General imaging equipment
        "surgery": 6,     # Surgical equipment
        "ophthalmology": 5,  # Laser, diagnostic equipment
        "physical therapy": 7,  # Therapy equipment
        "cardiology": 5,  # ECG, stress test, monitors
        "dermatology": 6, # Laser equipment
        "urgent care": 5, # Various diagnostic equipment
        "laboratory": 5,  # Lab equipment
    }

    # High-value specialties (more likely to finance)
    HIGH_VALUE_SPECIALTIES = [
        "dental", "radiology", "surgery", "ophthalmology",
        "dermatology", "plastic", "orthopedic", "cardiology",
        "imaging", "ambulatory", "urgent care"
    ]

    def detect_triggers(self, record: Dict[str, Any]) -> List[LoanTrigger]:
        """Detect healthcare-specific loan triggers."""
        triggers = super().detect_triggers(record)

        industry_data = record.get("industry_data", {})
        specialty = industry_data.get("Primary Specialty", "").lower()
        entity_type = industry_data.get("Entity Type", "")
        enumeration_date = industry_data.get("Enumeration Date", "")
        last_updated = industry_data.get("Last Updated", "")
        years = record.get("years_in_business")

        # Check for high-value specialty
        triggers.extend(self._check_specialty_triggers(specialty))

        # Check equipment lifecycle based on specialty and age
        triggers.extend(self._check_equipment_lifecycle(specialty, years))

        # Check for recent NPI activity
        triggers.extend(self._check_recent_activity(enumeration_date, last_updated))

        # Check for organization type (better financing candidates)
        if entity_type == "Organization":
            triggers.append(LoanTrigger(
                trigger_type=TriggerType.GROWTH_SIGNAL,
                priority=TriggerPriority.MEDIUM,
                name="Organization Entity",
                description="Healthcare organization (vs solo practitioner) - higher financing potential",
                score_boost=5,
                details={"entity_type": entity_type}
            ))

        return triggers

    def _check_specialty_triggers(self, specialty: str) -> List[LoanTrigger]:
        """Check for high-value specialty triggers."""
        triggers = []

        for high_value in self.HIGH_VALUE_SPECIALTIES:
            if high_value in specialty:
                triggers.append(LoanTrigger(
                    trigger_type=TriggerType.HIGH_VALUE_SPECIALTY,
                    priority=TriggerPriority.HIGH,
                    name=f"High-Value Specialty: {high_value.title()}",
                    description=f"{high_value.title()} practices have significant equipment financing needs",
                    score_boost=10,
                    details={"specialty": specialty, "category": high_value}
                ))
                break

        return triggers

    def _check_equipment_lifecycle(self, specialty: str, years: Optional[float]) -> List[LoanTrigger]:
        """Check if practice is in equipment replacement cycle."""
        triggers = []

        if years is None:
            return triggers

        # Find matching equipment cycle
        for spec_key, cycle_years in self.EQUIPMENT_CYCLES.items():
            if spec_key in specialty:
                # Check if near replacement cycle (within 1 year)
                if years > 0 and (years % cycle_years) <= 1:
                    triggers.append(LoanTrigger(
                        trigger_type=TriggerType.EQUIPMENT_LIFECYCLE,
                        priority=TriggerPriority.HIGH,
                        name=f"{spec_key.title()} Equipment Cycle",
                        description=f"Practice is ~{int(years)} years old - {spec_key} equipment typically replaced every {cycle_years} years",
                        score_boost=15,
                        details={
                            "specialty": spec_key,
                            "cycle_years": cycle_years,
                            "practice_age": years
                        }
                    ))
                # Check if approaching cycle (within 2 years)
                elif years > 0 and (years % cycle_years) <= 2:
                    triggers.append(LoanTrigger(
                        trigger_type=TriggerType.EQUIPMENT_LIFECYCLE,
                        priority=TriggerPriority.MEDIUM,
                        name=f"Approaching {spec_key.title()} Refresh",
                        description=f"Practice approaching equipment refresh cycle",
                        score_boost=8,
                        details={
                            "specialty": spec_key,
                            "cycle_years": cycle_years,
                            "practice_age": years
                        }
                    ))
                break

        return triggers

    def _check_recent_activity(self, enumeration_date: str, last_updated: str) -> List[LoanTrigger]:
        """Check for recent NPI activity indicating changes."""
        triggers = []

        # Check if recently enumerated (new practice)
        if enumeration_date:
            try:
                enum_year = int(enumeration_date.split("-")[0])
                if self.current_year - enum_year <= 1:
                    triggers.append(LoanTrigger(
                        trigger_type=TriggerType.NEW_BUSINESS,
                        priority=TriggerPriority.HIGH,
                        name="Recently Established Practice",
                        description=f"NPI enumerated in {enum_year} - new practice likely needs equipment",
                        score_boost=20,
                        details={"enumeration_year": enum_year}
                    ))
            except (ValueError, IndexError):
                pass

        # Check if recently updated (indicates activity/changes)
        if last_updated:
            try:
                update_year = int(last_updated.split("-")[0])
                update_month = int(last_updated.split("-")[1])
                months_since = (self.current_year - update_year) * 12 + (self.current_month - update_month)

                if months_since <= 6:
                    triggers.append(LoanTrigger(
                        trigger_type=TriggerType.RECENT_ACTIVITY,
                        priority=TriggerPriority.MEDIUM,
                        name="Recent NPI Update",
                        description="NPI recently updated - may indicate practice changes or expansion",
                        score_boost=5,
                        details={"last_updated": last_updated, "months_since": months_since}
                    ))
            except (ValueError, IndexError):
                pass

        return triggers


class ConstructionTriggerDetector(LoanTriggerDetector):
    """
    Construction-specific loan trigger detection.

    Detects triggers like:
    - Pre-season equipment needs
    - Contract/project signals
    - Equipment age/replacement
    - Growth indicators
    """

    # Construction seasons vary by region
    PEAK_SEASONS = {
        "north": [4, 5, 6, 7, 8, 9, 10],  # Apr-Oct
        "south": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12],  # Year-round
    }

    # Equipment cycles by contractor type (years)
    EQUIPMENT_CYCLES = {
        "heavy": 5,       # Heavy equipment (excavators, loaders)
        "general": 7,     # General construction equipment
        "electrical": 8,  # Tools and equipment
        "hvac": 6,        # HVAC equipment
        "plumbing": 8,    # Tools and equipment
        "concrete": 5,    # Concrete equipment
        "roofing": 6,     # Roofing equipment
        "landscaping": 5, # Landscaping equipment
    }

    # High-value contractor types
    HIGH_VALUE_TYPES = [
        "heavy", "civil", "general contractor", "commercial",
        "industrial", "infrastructure", "highway", "bridge"
    ]

    def detect_triggers(self, record: Dict[str, Any]) -> List[LoanTrigger]:
        """Detect construction-specific loan triggers."""
        triggers = super().detect_triggers(record)

        industry_data = record.get("industry_data", {})
        contractor_type = industry_data.get("Contractor Type", "").lower()
        incorporation_date = industry_data.get("Incorporation Date", "")
        years = record.get("years_in_business")
        state = record.get("state", "")

        # Check contractor type triggers
        triggers.extend(self._check_contractor_type_triggers(contractor_type))

        # Check seasonal triggers for construction
        triggers.extend(self._check_construction_seasonality(state))

        # Check equipment lifecycle
        triggers.extend(self._check_equipment_lifecycle(contractor_type, years))

        # Check for recent incorporation
        triggers.extend(self._check_new_business(incorporation_date))

        return triggers

    def _check_contractor_type_triggers(self, contractor_type: str) -> List[LoanTrigger]:
        """Check for high-value contractor type triggers."""
        triggers = []

        for high_value in self.HIGH_VALUE_TYPES:
            if high_value in contractor_type:
                triggers.append(LoanTrigger(
                    trigger_type=TriggerType.HIGH_VALUE_SPECIALTY,
                    priority=TriggerPriority.HIGH,
                    name=f"High-Value Contractor: {contractor_type.title()}",
                    description=f"{contractor_type.title()} contractors have significant equipment financing needs",
                    score_boost=10,
                    details={"contractor_type": contractor_type}
                ))
                break

        return triggers

    def _check_construction_seasonality(self, state: str) -> List[LoanTrigger]:
        """Check for construction seasonal triggers."""
        triggers = []

        # Northern states have distinct seasons
        northern_states = ["WA", "OR", "MT", "ND", "SD", "MN", "WI", "MI", "NY", "VT", "NH", "ME", "MA", "CT", "RI"]

        if state.upper() in northern_states:
            # Pre-season (Feb-Mar) is prime time for equipment financing
            if self.current_month in [2, 3]:
                triggers.append(LoanTrigger(
                    trigger_type=TriggerType.SEASONALITY,
                    priority=TriggerPriority.HIGH,
                    name="Pre-Season Equipment Timing",
                    description="Pre-construction season - contractors preparing equipment for busy season",
                    score_boost=15,
                    details={"season": "pre_season", "region": "northern"}
                ))
            # End of season (Oct-Nov) - planning for next year
            elif self.current_month in [10, 11]:
                triggers.append(LoanTrigger(
                    trigger_type=TriggerType.SEASONALITY,
                    priority=TriggerPriority.MEDIUM,
                    name="Season-End Planning",
                    description="End of construction season - contractors planning next year's equipment needs",
                    score_boost=10,
                    details={"season": "end_season", "region": "northern"}
                ))
        else:
            # Southern/year-round states
            if self.current_month in [1, 2]:
                triggers.append(LoanTrigger(
                    trigger_type=TriggerType.SEASONALITY,
                    priority=TriggerPriority.MEDIUM,
                    name="New Year Equipment Planning",
                    description="Start of year - good time for equipment upgrades",
                    score_boost=8,
                    details={"season": "new_year", "region": "southern"}
                ))

        return triggers

    def _check_equipment_lifecycle(self, contractor_type: str, years: Optional[float]) -> List[LoanTrigger]:
        """Check equipment replacement cycles for construction."""
        triggers = []

        if years is None:
            return triggers

        for type_key, cycle_years in self.EQUIPMENT_CYCLES.items():
            if type_key in contractor_type:
                if years > 0 and (years % cycle_years) <= 1:
                    triggers.append(LoanTrigger(
                        trigger_type=TriggerType.EQUIPMENT_LIFECYCLE,
                        priority=TriggerPriority.HIGH,
                        name=f"{type_key.title()} Equipment Replacement",
                        description=f"Business is ~{int(years)} years old - {type_key} equipment typically replaced every {cycle_years} years",
                        score_boost=15,
                        details={
                            "contractor_type": type_key,
                            "cycle_years": cycle_years,
                            "business_age": years
                        }
                    ))
                break

        return triggers

    def _check_new_business(self, incorporation_date: str) -> List[LoanTrigger]:
        """Check for recently incorporated businesses."""
        triggers = []

        if incorporation_date:
            try:
                inc_year = int(str(incorporation_date)[:4])
                years_since = self.current_year - inc_year

                if years_since <= 2:
                    triggers.append(LoanTrigger(
                        trigger_type=TriggerType.NEW_BUSINESS,
                        priority=TriggerPriority.HIGH,
                        name="Newly Incorporated",
                        description=f"Incorporated in {inc_year} - new contractors need equipment financing",
                        score_boost=15,
                        details={"incorporation_year": inc_year, "years_since": years_since}
                    ))
            except (ValueError, TypeError):
                pass

        return triggers


class AviationTriggerDetector(LoanTriggerDetector):
    """
    Aviation-specific loan trigger detection.

    Detects triggers like:
    - Fleet age and replacement needs
    - Regulatory compliance requirements
    - Fleet expansion signals
    - Maintenance/upgrade cycles
    """

    # Aircraft replacement/upgrade triggers by age
    AIRCRAFT_AGE_THRESHOLDS = {
        "major_overhaul": 12,    # Major maintenance/overhaul
        "avionics_upgrade": 10,  # Avionics modernization
        "replacement": 20,       # Consider replacement
    }

    # Engine overhaul intervals (flight hours, but we use age as proxy)
    ENGINE_CYCLES = {
        "turbine": 8,      # Turbine engines (expensive)
        "reciprocating": 6,  # Piston engines
    }

    def detect_triggers(self, record: Dict[str, Any]) -> List[LoanTrigger]:
        """Detect aviation-specific loan triggers."""
        triggers = super().detect_triggers(record)

        industry_data = record.get("industry_data", {})
        aircraft_count = industry_data.get("Aircraft Count", 0)
        owner_type = industry_data.get("Owner Type", "")
        engine_types = industry_data.get("Engine Types", "")
        newest_year = industry_data.get("Newest Aircraft Year", 0)
        n_numbers = industry_data.get("N-Numbers", "")

        # Check fleet size triggers
        triggers.extend(self._check_fleet_triggers(aircraft_count))

        # Check aircraft age triggers
        triggers.extend(self._check_aircraft_age_triggers(newest_year, engine_types))

        # Check owner type triggers
        triggers.extend(self._check_owner_type_triggers(owner_type))

        # Check for turbine aircraft (high value)
        if "turbo" in engine_types.lower():
            triggers.append(LoanTrigger(
                trigger_type=TriggerType.HIGH_VALUE_SPECIALTY,
                priority=TriggerPriority.HIGH,
                name="Turbine Aircraft Operator",
                description="Operates turbine aircraft - high-value financing opportunity",
                score_boost=15,
                details={"engine_types": engine_types}
            ))

        return triggers

    def _check_fleet_triggers(self, aircraft_count: int) -> List[LoanTrigger]:
        """Check for fleet-based triggers."""
        triggers = []

        if aircraft_count >= 5:
            triggers.append(LoanTrigger(
                trigger_type=TriggerType.GROWTH_SIGNAL,
                priority=TriggerPriority.HIGH,
                name="Fleet Operator",
                description=f"Operates {aircraft_count} aircraft - likely needs ongoing fleet financing",
                score_boost=15,
                details={"aircraft_count": aircraft_count}
            ))
        elif aircraft_count >= 3:
            triggers.append(LoanTrigger(
                trigger_type=TriggerType.EXPANSION,
                priority=TriggerPriority.MEDIUM,
                name="Growing Fleet",
                description=f"Operates {aircraft_count} aircraft - may be expanding fleet",
                score_boost=10,
                details={"aircraft_count": aircraft_count}
            ))

        return triggers

    def _check_aircraft_age_triggers(self, newest_year: int, engine_types: str) -> List[LoanTrigger]:
        """Check for aircraft age-related triggers."""
        triggers = []

        if not newest_year or newest_year == 0:
            return triggers

        aircraft_age = self.current_year - newest_year

        # Check for replacement timing
        if aircraft_age >= 15:
            triggers.append(LoanTrigger(
                trigger_type=TriggerType.FLEET_AGE,
                priority=TriggerPriority.HIGH,
                name="Aging Fleet",
                description=f"Newest aircraft is {aircraft_age}+ years old - strong replacement/upgrade opportunity",
                score_boost=20,
                details={"newest_year": newest_year, "age": aircraft_age}
            ))
        elif aircraft_age >= 10:
            triggers.append(LoanTrigger(
                trigger_type=TriggerType.EQUIPMENT_LIFECYCLE,
                priority=TriggerPriority.MEDIUM,
                name="Avionics Upgrade Cycle",
                description=f"Aircraft ~{aircraft_age} years old - may need avionics upgrade",
                score_boost=10,
                details={"newest_year": newest_year, "age": aircraft_age}
            ))
        elif aircraft_age <= 3:
            # Recent buyer - may finance again
            triggers.append(LoanTrigger(
                trigger_type=TriggerType.RECENT_ACTIVITY,
                priority=TriggerPriority.HIGH,
                name="Recent Aircraft Buyer",
                description=f"Recently acquired aircraft ({newest_year}) - active in market",
                score_boost=15,
                details={"newest_year": newest_year, "age": aircraft_age}
            ))

        return triggers

    def _check_owner_type_triggers(self, owner_type: str) -> List[LoanTrigger]:
        """Check for owner type triggers."""
        triggers = []

        if owner_type in ["Corporation", "LLC"]:
            triggers.append(LoanTrigger(
                trigger_type=TriggerType.GROWTH_SIGNAL,
                priority=TriggerPriority.MEDIUM,
                name=f"Business Entity ({owner_type})",
                description=f"{owner_type} ownership - better financing candidate than individual",
                score_boost=5,
                details={"owner_type": owner_type}
            ))

        return triggers


class AutoDealerTriggerDetector(LoanTriggerDetector):
    """
    Auto dealer-specific loan trigger detection.

    Detects triggers like:
    - Floor plan financing needs
    - New model year inventory timing
    - Equipment upgrade cycles
    - Facility expansion signals
    """

    # Equipment cycles for dealerships (years)
    EQUIPMENT_CYCLES = {
        "lifts": 10,           # Vehicle lifts
        "diagnostic": 5,       # Diagnostic equipment
        "pos": 7,              # POS/computer systems
        "signage": 8,          # Signage and displays
    }

    # High-value dealer types
    HIGH_VALUE_TYPES = [
        "new car", "rv", "motorhome", "commercial truck",
        "heavy equipment", "franchise"
    ]

    def detect_triggers(self, record: Dict[str, Any]) -> List[LoanTrigger]:
        """Detect auto dealer-specific loan triggers."""
        triggers = super().detect_triggers(record)

        industry_data = record.get("industry_data", {})
        dealer_type = industry_data.get("Dealer Type", "").lower()
        incorporation_date = industry_data.get("Incorporation Date", "")
        years = record.get("years_in_business")

        # Check dealer type triggers
        triggers.extend(self._check_dealer_type_triggers(dealer_type))

        # Check inventory timing (new model year)
        triggers.extend(self._check_inventory_timing())

        # Check equipment lifecycle
        triggers.extend(self._check_equipment_lifecycle(years))

        # Check for new dealer
        triggers.extend(self._check_new_dealer(incorporation_date))

        return triggers

    def _check_dealer_type_triggers(self, dealer_type: str) -> List[LoanTrigger]:
        """Check for high-value dealer type triggers."""
        triggers = []

        for high_value in self.HIGH_VALUE_TYPES:
            if high_value in dealer_type:
                triggers.append(LoanTrigger(
                    trigger_type=TriggerType.HIGH_VALUE_SPECIALTY,
                    priority=TriggerPriority.HIGH,
                    name=f"High-Value Dealer: {dealer_type.title()}",
                    description=f"{dealer_type.title()} dealers have significant inventory financing needs",
                    score_boost=15,
                    details={"dealer_type": dealer_type}
                ))
                break

        return triggers

    def _check_inventory_timing(self) -> List[LoanTrigger]:
        """Check for new model year inventory timing."""
        triggers = []

        # Aug-Oct is new model year season - dealers need floor plan financing
        if self.current_month in [8, 9, 10]:
            triggers.append(LoanTrigger(
                trigger_type=TriggerType.SEASONALITY,
                priority=TriggerPriority.HIGH,
                name="New Model Year Season",
                description="New model year inventory arriving - dealers need floor plan financing",
                score_boost=20,
                details={"season": "new_model_year", "months": [8, 9, 10]}
            ))
        # Jan-Feb is slow season - good time for equipment upgrades
        elif self.current_month in [1, 2]:
            triggers.append(LoanTrigger(
                trigger_type=TriggerType.SEASONALITY,
                priority=TriggerPriority.MEDIUM,
                name="Off-Season Equipment Time",
                description="Slower sales season - good time for facility/equipment upgrades",
                score_boost=10,
                details={"season": "off_season", "months": [1, 2]}
            ))

        return triggers

    def _check_equipment_lifecycle(self, years: Optional[float]) -> List[LoanTrigger]:
        """Check equipment replacement cycles for dealerships."""
        triggers = []

        if years is None:
            return triggers

        # Check lift replacement cycle (10 years)
        if years > 0 and years >= 8 and (years % 10) <= 2:
            triggers.append(LoanTrigger(
                trigger_type=TriggerType.EQUIPMENT_LIFECYCLE,
                priority=TriggerPriority.HIGH,
                name="Service Equipment Upgrade",
                description=f"Dealership is ~{int(years)} years old - likely needs lift/diagnostic equipment refresh",
                score_boost=15,
                details={"business_age": years, "equipment_type": "service"}
            ))

        # Check POS/technology upgrade (5-7 years)
        if years > 0 and years >= 5 and (years % 6) <= 1:
            triggers.append(LoanTrigger(
                trigger_type=TriggerType.EQUIPMENT_LIFECYCLE,
                priority=TriggerPriority.MEDIUM,
                name="Technology Refresh Cycle",
                description="May need POS, DMS, or computer system upgrades",
                score_boost=10,
                details={"business_age": years, "equipment_type": "technology"}
            ))

        return triggers

    def _check_new_dealer(self, incorporation_date: str) -> List[LoanTrigger]:
        """Check for newly established dealers."""
        triggers = []

        if incorporation_date:
            try:
                inc_year = int(str(incorporation_date)[:4])
                years_since = self.current_year - inc_year

                if years_since <= 2:
                    triggers.append(LoanTrigger(
                        trigger_type=TriggerType.NEW_BUSINESS,
                        priority=TriggerPriority.HIGH,
                        name="New Dealership",
                        description=f"Established in {inc_year} - new dealers need floor plan and equipment financing",
                        score_boost=20,
                        details={"incorporation_year": inc_year, "years_since": years_since}
                    ))
            except (ValueError, TypeError):
                pass

        return triggers


class RestaurantTriggerDetector(LoanTriggerDetector):
    """
    Restaurant-specific loan trigger detection.

    Detects triggers like:
    - Equipment replacement cycles
    - Expansion signals
    - Seasonal patterns
    - Renovation timing
    """

    # Equipment cycles for restaurants (years)
    EQUIPMENT_CYCLES = {
        "kitchen": 7,          # Commercial kitchen equipment
        "refrigeration": 8,    # Walk-ins, reach-ins
        "hvac": 10,            # HVAC systems
        "pos": 5,              # POS systems
        "furniture": 6,        # Tables, chairs, booths
    }

    # High-value restaurant types
    HIGH_VALUE_TYPES = [
        "full service", "catering", "bakery", "steakhouse",
        "fine dining", "brewery", "distillery"
    ]

    def detect_triggers(self, record: Dict[str, Any]) -> List[LoanTrigger]:
        """Detect restaurant-specific loan triggers."""
        triggers = super().detect_triggers(record)

        industry_data = record.get("industry_data", {})
        restaurant_type = industry_data.get("Restaurant Type", "").lower()
        health_grade = industry_data.get("Health Grade", "")
        years = record.get("years_in_business")

        # Check restaurant type triggers
        triggers.extend(self._check_restaurant_type_triggers(restaurant_type))

        # Check equipment lifecycle
        triggers.extend(self._check_equipment_lifecycle(years))

        # Check renovation timing (post-inspection)
        triggers.extend(self._check_renovation_timing(health_grade))

        # Check seasonal patterns
        triggers.extend(self._check_seasonal_patterns())

        return triggers

    def _check_restaurant_type_triggers(self, restaurant_type: str) -> List[LoanTrigger]:
        """Check for high-value restaurant type triggers."""
        triggers = []

        for high_value in self.HIGH_VALUE_TYPES:
            if high_value in restaurant_type:
                triggers.append(LoanTrigger(
                    trigger_type=TriggerType.HIGH_VALUE_SPECIALTY,
                    priority=TriggerPriority.HIGH,
                    name=f"High-Value Restaurant: {restaurant_type.title()}",
                    description=f"{restaurant_type.title()} restaurants have significant equipment needs",
                    score_boost=15,
                    details={"restaurant_type": restaurant_type}
                ))
                break

        # Bakeries always need specialized equipment
        if "bakery" in restaurant_type:
            triggers.append(LoanTrigger(
                trigger_type=TriggerType.HIGH_VALUE_SPECIALTY,
                priority=TriggerPriority.HIGH,
                name="Bakery Equipment Needs",
                description="Bakeries require expensive specialized equipment (ovens, mixers, proofers)",
                score_boost=15,
                details={"restaurant_type": restaurant_type}
            ))

        return triggers

    def _check_equipment_lifecycle(self, years: Optional[float]) -> List[LoanTrigger]:
        """Check equipment replacement cycles for restaurants."""
        triggers = []

        if years is None:
            return triggers

        # Kitchen equipment cycle (7 years)
        if years > 0 and (years % 7) <= 1:
            triggers.append(LoanTrigger(
                trigger_type=TriggerType.EQUIPMENT_LIFECYCLE,
                priority=TriggerPriority.HIGH,
                name="Kitchen Equipment Refresh",
                description=f"Restaurant is ~{int(years)} years old - kitchen equipment typically replaced every 7 years",
                score_boost=15,
                details={"business_age": years, "equipment_type": "kitchen"}
            ))

        # Refrigeration cycle (8 years)
        if years > 0 and years >= 6 and (years % 8) <= 2:
            triggers.append(LoanTrigger(
                trigger_type=TriggerType.EQUIPMENT_LIFECYCLE,
                priority=TriggerPriority.MEDIUM,
                name="Refrigeration Upgrade",
                description="May need walk-in cooler/freezer or refrigeration upgrades",
                score_boost=10,
                details={"business_age": years, "equipment_type": "refrigeration"}
            ))

        # POS refresh (5 years)
        if years > 0 and years >= 4 and (years % 5) <= 1:
            triggers.append(LoanTrigger(
                trigger_type=TriggerType.EQUIPMENT_LIFECYCLE,
                priority=TriggerPriority.MEDIUM,
                name="POS System Upgrade",
                description="May need POS system upgrade or replacement",
                score_boost=8,
                details={"business_age": years, "equipment_type": "pos"}
            ))

        return triggers

    def _check_renovation_timing(self, health_grade: str) -> List[LoanTrigger]:
        """Check for renovation triggers based on health inspection."""
        triggers = []

        # B or C grade might prompt renovation/upgrades
        if health_grade in ["B", "C"]:
            triggers.append(LoanTrigger(
                trigger_type=TriggerType.REGULATORY,
                priority=TriggerPriority.MEDIUM,
                name="Post-Inspection Upgrades",
                description=f"Health grade {health_grade} - may be considering equipment/facility upgrades",
                score_boost=10,
                details={"health_grade": health_grade}
            ))

        return triggers

    def _check_seasonal_patterns(self) -> List[LoanTrigger]:
        """Check for seasonal patterns in restaurant industry."""
        triggers = []

        # Jan-Feb is slow season - good for equipment upgrades
        if self.current_month in [1, 2]:
            triggers.append(LoanTrigger(
                trigger_type=TriggerType.SEASONALITY,
                priority=TriggerPriority.MEDIUM,
                name="Off-Season Renovation Time",
                description="Post-holiday slow season - ideal time for renovations and equipment upgrades",
                score_boost=10,
                details={"season": "post_holiday", "months": [1, 2]}
            ))

        # Pre-summer (Apr-May) - preparing for busy season
        elif self.current_month in [4, 5]:
            triggers.append(LoanTrigger(
                trigger_type=TriggerType.SEASONALITY,
                priority=TriggerPriority.MEDIUM,
                name="Pre-Summer Preparation",
                description="Preparing for busy summer season - may need equipment or patio upgrades",
                score_boost=8,
                details={"season": "pre_summer", "months": [4, 5]}
            ))

        return triggers


def get_trigger_detector(industry: str) -> LoanTriggerDetector:
    """
    Factory function to get the appropriate trigger detector for an industry.

    Args:
        industry: Industry name (healthcare, construction, aviation, etc.)

    Returns:
        Appropriate LoanTriggerDetector subclass instance
    """
    industry_lower = industry.lower()

    if "healthcare" in industry_lower or "npi" in industry_lower:
        return HealthcareTriggerDetector()
    elif "construction" in industry_lower or "contractor" in industry_lower:
        return ConstructionTriggerDetector()
    elif "aviation" in industry_lower or "faa" in industry_lower or "aircraft" in industry_lower:
        return AviationTriggerDetector()
    elif "auto" in industry_lower or "dealer" in industry_lower or "car" in industry_lower:
        return AutoDealerTriggerDetector()
    elif "restaurant" in industry_lower or "food" in industry_lower:
        return RestaurantTriggerDetector()
    else:
        return LoanTriggerDetector()


def format_triggers_for_display(triggers: List[LoanTrigger]) -> Dict[str, Any]:
    """
    Format triggers for display in UI/reports.

    Args:
        triggers: List of detected triggers

    Returns:
        Formatted dictionary with trigger summary and details
    """
    if not triggers:
        return {
            "count": 0,
            "priority": None,
            "score_boost": 0,
            "triggers": [],
            "summary": "No loan triggers detected"
        }

    # Sort by priority and score boost
    priority_order = {"high": 3, "medium": 2, "low": 1}
    sorted_triggers = sorted(
        triggers,
        key=lambda t: (priority_order.get(t.priority.value, 0), t.score_boost),
        reverse=True
    )

    highest_priority = sorted_triggers[0].priority.value if sorted_triggers else None
    total_boost = sum(t.score_boost for t in triggers)

    # Build summary
    high_count = sum(1 for t in triggers if t.priority == TriggerPriority.HIGH)
    if high_count > 0:
        summary = f"{high_count} high-priority trigger(s) detected - strong financing candidate"
    elif len(triggers) > 0:
        summary = f"{len(triggers)} trigger(s) detected - good financing potential"
    else:
        summary = "No loan triggers detected"

    return {
        "count": len(triggers),
        "priority": highest_priority,
        "score_boost": total_boost,
        "triggers": [t.to_dict() for t in sorted_triggers],
        "summary": summary
    }
