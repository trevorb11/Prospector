"""
Auto Dealer Prospector
======================

Finds automotive dealership prospects using state licensing databases
and business registries.

Auto dealers are excellent financing prospects because they need:
- Floor plan financing (inventory loans)
- Equipment financing (lifts, diagnostic equipment)
- Real estate/facility loans
- Working capital for operations
"""

import requests
from typing import Any, Dict, List, Optional
from datetime import datetime

from ..core.base import IndustryProspector, ProspectRecord
from ..core.scoring import RuleType


class AutoDealerProspector(IndustryProspector):
    """
    Prospector for automotive dealerships.

    Uses state business registries and dealer licensing data to find
    car dealerships that may need financing.
    """

    # Dealer types and their financing potential
    DEALER_TYPES = {
        "new": "New Car Dealer",
        "used": "Used Car Dealer",
        "wholesale": "Wholesale Dealer",
        "motorcycle": "Motorcycle Dealer",
        "rv": "RV/Motorhome Dealer",
        "boat": "Boat Dealer",
        "truck": "Commercial Truck Dealer",
        "equipment": "Heavy Equipment Dealer",
    }

    # Keywords to identify dealer types from business names
    DEALER_KEYWORDS = {
        "new": ["new car", "new vehicle", "authorized dealer", "franchise"],
        "used": ["used car", "used auto", "pre-owned", "preowned", "auto sales"],
        "wholesale": ["wholesale", "auction", "dealer only"],
        "motorcycle": ["motorcycle", "harley", "honda cycle", "yamaha", "kawasaki", "powersports"],
        "rv": ["rv", "motorhome", "camper", "recreational vehicle", "trailer sales"],
        "boat": ["boat", "marine", "yacht", "watercraft"],
        "truck": ["truck center", "commercial truck", "freightliner", "peterbilt", "kenworth"],
        "equipment": ["equipment dealer", "tractor dealer", "caterpillar", "john deere", "kubota"],
    }

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize the auto dealer prospector.

        Config options:
            target_states: List of state abbreviations to search
            dealer_types: List of dealer types to include (new, used, etc.)
            limit_per_state: Max records per state
        """
        self.config = config or {}
        self.target_states = self.config.get("target_states", ["FL"])
        self.dealer_types = self.config.get("dealer_types", None)  # None = all types
        self.limit_per_state = self.config.get("limit_per_state", 500)
        self._prospects: List[ProspectRecord] = []

    def get_industry_name(self) -> str:
        return "Auto Dealers"

    def fetch_prospects(self) -> List[Dict[str, Any]]:
        """Fetch auto dealer data from business registries."""
        print(f"\nFetching auto dealer prospects...")
        print(f"  States: {', '.join(self.target_states)}")

        all_records = []

        for state in self.target_states:
            state_records = self._fetch_state_data(state)
            all_records.extend(state_records)

        print(f"\nTotal raw records: {len(all_records)}")
        return all_records

    def _fetch_state_data(self, state: str) -> List[Dict[str, Any]]:
        """
        Fetch dealer data for a specific state.

        Uses OpenCorporates API to search for automotive businesses.
        """
        records = []

        # Search terms for finding auto dealers
        search_terms = [
            "auto dealer",
            "car dealer",
            "auto sales",
            "motor sales",
            "automotive group",
            "car sales",
            "used cars",
            "auto mart",
            "motors inc",
            "motors llc",
        ]

        # State code mapping for OpenCorporates
        state_codes = {
            "AL": "us_al", "AK": "us_ak", "AZ": "us_az", "AR": "us_ar", "CA": "us_ca",
            "CO": "us_co", "CT": "us_ct", "DE": "us_de", "FL": "us_fl", "GA": "us_ga",
            "HI": "us_hi", "ID": "us_id", "IL": "us_il", "IN": "us_in", "IA": "us_ia",
            "KS": "us_ks", "KY": "us_ky", "LA": "us_la", "ME": "us_me", "MD": "us_md",
            "MA": "us_ma", "MI": "us_mi", "MN": "us_mn", "MS": "us_ms", "MO": "us_mo",
            "MT": "us_mt", "NE": "us_ne", "NV": "us_nv", "NH": "us_nh", "NJ": "us_nj",
            "NM": "us_nm", "NY": "us_ny", "NC": "us_nc", "ND": "us_nd", "OH": "us_oh",
            "OK": "us_ok", "OR": "us_or", "PA": "us_pa", "RI": "us_ri", "SC": "us_sc",
            "SD": "us_sd", "TN": "us_tn", "TX": "us_tx", "UT": "us_ut", "VT": "us_vt",
            "VA": "us_va", "WA": "us_wa", "WV": "us_wv", "WI": "us_wi", "WY": "us_wy",
        }

        jurisdiction = state_codes.get(state.upper(), f"us_{state.lower()}")
        seen_companies = set()

        for term in search_terms:
            if len(records) >= self.limit_per_state:
                break

            try:
                url = "https://api.opencorporates.com/v0.4/companies/search"
                params = {
                    "q": term,
                    "jurisdiction_code": jurisdiction,
                    "per_page": 50,
                    "current_status": "Active",
                }

                response = requests.get(url, params=params, timeout=15)

                if response.status_code == 200:
                    data = response.json()
                    companies = data.get("results", {}).get("companies", [])

                    for item in companies:
                        company = item.get("company", {})
                        company_name = company.get("name", "")

                        # Deduplicate
                        if company_name.upper() in seen_companies:
                            continue
                        seen_companies.add(company_name.upper())

                        # Must look like a dealer
                        if not self._is_auto_dealer(company_name):
                            continue

                        record = {
                            "company_name": company_name,
                            "company_number": company.get("company_number"),
                            "jurisdiction": company.get("jurisdiction_code", "").upper(),
                            "state": state.upper(),
                            "incorporation_date": company.get("incorporation_date"),
                            "company_type": company.get("company_type"),
                            "current_status": company.get("current_status"),
                            "registered_address": company.get("registered_address_in_full"),
                            "source": "OpenCorporates",
                        }
                        records.append(record)

                        if len(records) >= self.limit_per_state:
                            break

            except requests.RequestException as e:
                print(f"    Warning: Error fetching {term} for {state}: {e}")
                continue

        print(f"  Fetching {state}... {len(records)} dealers found")
        return records

    def _is_auto_dealer(self, name: str) -> bool:
        """Check if a company name looks like an auto dealer."""
        name_lower = name.lower()

        # Must contain dealer-related keywords
        dealer_indicators = [
            "auto", "car", "motor", "vehicle", "dealer", "sales",
            "automotive", "cars", "truck", "rv", "motorcycle",
        ]

        has_indicator = any(ind in name_lower for ind in dealer_indicators)
        if not has_indicator:
            return False

        # Exclude non-dealers
        exclusions = [
            "parts", "repair", "service", "body shop", "collision",
            "rental", "leasing only", "insurance", "finance company",
            "warranty", "detailing", "wash", "tire",
        ]

        has_exclusion = any(exc in name_lower for exc in exclusions)
        return not has_exclusion

    def _determine_dealer_type(self, name: str) -> str:
        """Determine the type of dealer from the company name."""
        name_lower = name.lower()

        for dealer_type, keywords in self.DEALER_KEYWORDS.items():
            if any(kw in name_lower for kw in keywords):
                return self.DEALER_TYPES.get(dealer_type, "Auto Dealer")

        # Default based on common patterns
        if "new" in name_lower and "used" not in name_lower:
            return "New Car Dealer"
        elif "used" in name_lower or "pre-owned" in name_lower:
            return "Used Car Dealer"

        return "Auto Dealer"

    def parse_record(self, raw: Dict[str, Any]) -> ProspectRecord:
        """Parse raw dealer data into a ProspectRecord."""
        company_name = raw.get("company_name", "Unknown")
        dealer_type = self._determine_dealer_type(company_name)

        # Calculate years in business
        years = None
        inc_date = raw.get("incorporation_date")
        if inc_date:
            try:
                inc_year = int(str(inc_date)[:4])
                years = datetime.now().year - inc_year
            except (ValueError, TypeError):
                pass

        # Parse address
        address = raw.get("registered_address", "") or ""
        city = ""
        if address:
            # Try to extract city from address
            parts = address.split(",")
            if len(parts) >= 2:
                city = parts[-2].strip() if len(parts) >= 2 else ""

        return ProspectRecord(
            company_name=company_name,
            industry_id=raw.get("company_number"),
            address=address,
            city=city,
            state=raw.get("state", ""),
            years_in_business=years,
            industry_data={
                "Dealer Type": dealer_type,
                "Company Type": raw.get("company_type", ""),
                "Status": raw.get("current_status", ""),
                "Incorporation Date": inc_date,
            },
        )

    def get_scoring_rules(self) -> List[Dict[str, Any]]:
        """Return scoring rules for auto dealers."""
        return [
            # Base score
            {
                "name": "base_score",
                "field": "company_name",
                "rule_type": RuleType.PRESENCE,
                "points": 50,
            },
            # New car dealers (franchise) - highest value
            {
                "name": "new_car_dealer",
                "field": "industry_data.Dealer Type",
                "rule_type": RuleType.CONTAINS,
                "value": "New Car",
                "points": 30,
            },
            # RV dealers - high value inventory
            {
                "name": "rv_dealer",
                "field": "industry_data.Dealer Type",
                "rule_type": RuleType.CONTAINS,
                "value": "RV",
                "points": 25,
            },
            # Commercial truck dealers
            {
                "name": "truck_dealer",
                "field": "industry_data.Dealer Type",
                "rule_type": RuleType.CONTAINS,
                "value": "Truck",
                "points": 25,
            },
            # Equipment dealers
            {
                "name": "equipment_dealer",
                "field": "industry_data.Dealer Type",
                "rule_type": RuleType.CONTAINS,
                "value": "Equipment",
                "points": 25,
            },
            # Motorcycle/Powersports
            {
                "name": "motorcycle_dealer",
                "field": "industry_data.Dealer Type",
                "rule_type": RuleType.CONTAINS,
                "value": "Motorcycle",
                "points": 20,
            },
            # Used car dealers
            {
                "name": "used_car_dealer",
                "field": "industry_data.Dealer Type",
                "rule_type": RuleType.CONTAINS,
                "value": "Used",
                "points": 15,
            },
            # Established business (5+ years)
            {
                "name": "established_5plus",
                "field": "years_in_business",
                "rule_type": RuleType.RANGE,
                "min_value": 5,
                "max_value": 100,
                "points": 15,
            },
            # Newer business (good growth potential)
            {
                "name": "newer_business",
                "field": "years_in_business",
                "rule_type": RuleType.RANGE,
                "min_value": 1,
                "max_value": 3,
                "points": 10,
            },
            # Corporation (more formal structure)
            {
                "name": "corporation",
                "field": "industry_data.Company Type",
                "rule_type": RuleType.CONTAINS,
                "value": "Corporation",
                "points": 10,
            },
            # LLC
            {
                "name": "llc",
                "field": "industry_data.Company Type",
                "rule_type": RuleType.CONTAINS,
                "value": "LLC",
                "points": 5,
            },
        ]


def lookup_dealer(company_name: str, state: str = None) -> List[Dict[str, Any]]:
    """
    Search for an auto dealer by name.

    Args:
        company_name: Company name to search
        state: Optional state filter

    Returns:
        List of matching dealer records
    """
    config = {
        "target_states": [state] if state else ["FL", "TX", "CA"],
        "limit_per_state": 25,
    }

    prospector = AutoDealerProspector(config)

    # Search using OpenCorporates
    results = []
    jurisdiction = f"us_{state.lower()}" if state else None

    try:
        url = "https://api.opencorporates.com/v0.4/companies/search"
        params = {
            "q": company_name,
            "per_page": 25,
        }
        if jurisdiction:
            params["jurisdiction_code"] = jurisdiction

        response = requests.get(url, params=params, timeout=15)

        if response.status_code == 200:
            data = response.json()
            companies = data.get("results", {}).get("companies", [])

            for item in companies:
                company = item.get("company", {})
                name = company.get("name", "")

                if prospector._is_auto_dealer(name):
                    results.append({
                        "company_name": name,
                        "state": company.get("jurisdiction_code", "").replace("us_", "").upper(),
                        "status": company.get("current_status"),
                        "incorporation_date": company.get("incorporation_date"),
                        "dealer_type": prospector._determine_dealer_type(name),
                    })

    except requests.RequestException as e:
        print(f"Error searching: {e}")

    return results
