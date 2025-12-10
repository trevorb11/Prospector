"""
Construction Contractors Industry Prospector
=============================================

This module provides prospect finding for the construction industry using
multiple state contractor licensing databases.

Data Sources:
- California CSLB (Contractors State License Board)
- Texas TDLR (Texas Department of Licensing and Regulation)
- Florida DBPR (Department of Business and Professional Regulation)
- Other state licensing APIs where available

Note: Construction licensing is state-regulated, so this prospector aggregates
data from multiple state-specific sources.
"""

import requests
import time
import re
from typing import Any, Dict, List, Optional
from datetime import datetime
from bs4 import BeautifulSoup
import json

from ..core.base import IndustryProspector, ProspectRecord
from ..core.scoring import ScoringRule, RuleType


# State-specific API endpoints and data sources
STATE_APIS = {
    "CA": {
        "name": "California CSLB",
        "search_url": "https://www.cslb.ca.gov/OnlineServices/CheckLicenseII/CheckLicense.aspx",
        "api_available": False,  # No direct API, requires scraping
    },
    "TX": {
        "name": "Texas TDLR",
        "api_url": "https://www.tdlr.texas.gov/cimsfo/fosearch.asp",
        "api_available": False,
    },
    "FL": {
        "name": "Florida DBPR",
        "api_url": "https://www.myfloridalicense.com/wl11.asp",
        "api_available": False,
    },
}

# Construction license types (high-value for equipment financing)
HIGH_VALUE_LICENSE_TYPES = {
    "general": ["General Contractor", "General Building", "General Engineering", "GC", "CGC"],
    "specialty": [
        "Electrical", "Plumbing", "HVAC", "Mechanical", "Roofing",
        "Concrete", "Masonry", "Steel", "Demolition", "Excavation",
        "Paving", "Landscaping", "Solar", "Fire Protection"
    ],
    "heavy": [
        "Heavy Civil", "Highway", "Bridge", "Underground", "Pipeline",
        "Utility", "Marine", "Dredging"
    ],
}

# Open Corporates API for business data (free tier available)
OPENCORPORATES_API = "https://api.opencorporates.com/v0.4"


class ConstructionProspector(IndustryProspector):
    """
    Prospector for the construction industry using state licensing data.

    Since construction licensing is state-regulated, this prospector
    uses a combination of approaches:
    1. State licensing board APIs where available
    2. Business registry data
    3. SBA/government contractor databases

    Configuration options:
        target_states: List of state abbreviations to search
        license_types: Types of licenses to search for
        min_years_licensed: Minimum years with active license
        active_only: Only include active licenses
        limit_per_state: Maximum records per state
    """

    DEFAULT_CONFIG = {
        "target_states": ["FL", "TX", "CA", "GA", "NC", "AZ", "CO", "TN", "OH", "PA"],
        "license_types": ["general", "specialty", "heavy"],
        "min_years_licensed": 0,
        "active_only": True,
        "limit_per_state": 500,
        "include_specialty_types": None,  # If set, filter to specific types
    }

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize the construction prospector.

        Args:
            config: Configuration dictionary. Missing keys will use defaults.
        """
        merged_config = {**self.DEFAULT_CONFIG, **(config or {})}
        super().__init__(merged_config)

    def get_industry_name(self) -> str:
        return "Construction Contractors"

    def _fetch_sam_gov_contractors(self, state: str) -> List[Dict[str, Any]]:
        """
        Fetch construction contractors from SAM.gov (System for Award Management).

        SAM.gov contains federal contractor registrations and is publicly accessible.
        """
        records = []

        # SAM.gov API endpoint for entity search
        # Note: Requires API key for full access, but basic search is available
        sam_url = "https://api.sam.gov/entity-information/v2/entities"

        # NAICS codes for construction
        construction_naics = [
            "236", "237", "238",  # Construction main categories
            "236115", "236116", "236117", "236118",  # Residential building
            "236210", "236220",  # Commercial building
            "237110", "237120", "237130",  # Heavy civil
            "238110", "238120", "238130", "238140",  # Foundation, structure
            "238210", "238220",  # Electrical, plumbing
            "238310", "238320", "238330", "238340",  # Finishing
            "238910", "238990",  # Site prep, other specialty
        ]

        params = {
            "physicalAddressStateCode": state,
            "naicsCode": "23*",  # All construction NAICS
            "registrationStatus": "A",  # Active only
            "page": 0,
            "size": 100,
        }

        # Note: SAM.gov requires registration for API access
        # For now, we'll use an alternative approach

        return records

    def _fetch_from_business_registry(self, state: str) -> List[Dict[str, Any]]:
        """
        Fetch construction businesses from state business registries.

        Uses OpenCorporates or similar services for business data.
        """
        records = []

        # Construction-related keywords for business name search
        construction_keywords = [
            "construction", "contractor", "builder", "building",
            "roofing", "plumbing", "electrical", "hvac",
            "excavation", "paving", "concrete", "masonry"
        ]

        # OpenCorporates search (free tier: 500 searches/month)
        for keyword in construction_keywords[:3]:  # Limit to conserve quota
            url = f"{OPENCORPORATES_API}/companies/search"
            params = {
                "q": keyword,
                "jurisdiction_code": f"us_{state.lower()}",
                "current_status": "Active",
                "per_page": 30,
            }

            try:
                response = requests.get(url, params=params, timeout=30)
                if response.status_code == 200:
                    data = response.json()
                    companies = data.get("results", {}).get("companies", [])

                    for company_data in companies:
                        company = company_data.get("company", {})
                        records.append({
                            "company_name": company.get("name", ""),
                            "state": state,
                            "jurisdiction": company.get("jurisdiction_code", ""),
                            "company_number": company.get("company_number", ""),
                            "status": company.get("current_status", ""),
                            "incorporation_date": company.get("incorporation_date"),
                            "company_type": company.get("company_type", ""),
                            "registered_address": company.get("registered_address_in_full", ""),
                            "source": "OpenCorporates",
                        })

                time.sleep(0.5)  # Rate limiting

            except requests.exceptions.RequestException as e:
                continue

        return records

    def _generate_synthetic_prospects(self, state: str) -> List[Dict[str, Any]]:
        """
        Generate prospect templates based on typical construction company patterns.

        This is a placeholder that demonstrates the data structure.
        In production, this would be replaced with actual API integrations.

        For real data, consider:
        1. Partnering with data providers (D&B, InfoUSA, etc.)
        2. State-specific licensing board integrations
        3. SAM.gov contractor registration data
        """
        # Return empty list - real implementation would fetch from actual sources
        return []

    def _fetch_state_data(self, state: str) -> List[Dict[str, Any]]:
        """Fetch construction contractor data for a state."""
        all_records = []

        print(f"  Fetching {state}...", end="", flush=True)

        # Try multiple data sources
        # 1. Business registry data
        registry_records = self._fetch_from_business_registry(state)
        all_records.extend(registry_records)

        # 2. Add other sources as available

        # Deduplicate by company name
        seen_names = set()
        unique_records = []
        for record in all_records:
            name = record.get("company_name", "").lower().strip()
            if name and name not in seen_names:
                seen_names.add(name)
                unique_records.append(record)

        print(f" {len(unique_records)} records")
        return unique_records[:self.config["limit_per_state"]]

    def fetch_prospects(self) -> List[Dict[str, Any]]:
        """Fetch prospect data for all target states."""
        all_records = []

        print(f"\nFetching construction contractor prospects...")
        print(f"  States: {', '.join(self.config['target_states'])}")
        print(f"  Data sources: Business registries, OpenCorporates")
        print()

        for state in self.config["target_states"]:
            state_records = self._fetch_state_data(state)
            all_records.extend(state_records)
            time.sleep(0.5)

        print(f"\nTotal raw records: {len(all_records)}")
        return all_records

    @staticmethod
    def clean_phone_number(phone: Any) -> str:
        """Clean and format phone number."""
        if phone is None or phone == "":
            return ""
        digits = re.sub(r"\D", "", str(phone))
        if len(digits) == 10:
            return f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"
        elif len(digits) == 11 and digits[0] == "1":
            return f"({digits[1:4]}) {digits[4:7]}-{digits[7:]}"
        return str(phone) if phone else ""

    def _determine_contractor_type(self, company_name: str) -> str:
        """Determine contractor type from company name."""
        name_lower = company_name.lower()

        # Check for heavy/civil contractors
        heavy_keywords = ["highway", "bridge", "civil", "heavy", "paving", "asphalt", "grading", "excavat", "underground"]
        for kw in heavy_keywords:
            if kw in name_lower:
                return "Heavy/Civil"

        # Check for specialty contractors
        specialty_map = {
            "electric": "Electrical",
            "plumb": "Plumbing",
            "hvac": "HVAC",
            "heat": "HVAC",
            "air condition": "HVAC",
            "roof": "Roofing",
            "concrete": "Concrete",
            "mason": "Masonry",
            "steel": "Steel/Metal",
            "demol": "Demolition",
            "landscap": "Landscaping",
            "solar": "Solar",
            "fire": "Fire Protection",
            "paint": "Painting",
            "flooring": "Flooring",
            "drywall": "Drywall",
            "insul": "Insulation",
            "window": "Windows/Doors",
            "glass": "Glazing",
            "tile": "Tile/Stone",
            "pool": "Pool/Spa",
            "fence": "Fencing",
        }

        for kw, specialty in specialty_map.items():
            if kw in name_lower:
                return specialty

        # Check for general contractors
        general_keywords = ["general", "builder", "construction co", "contracting", "development"]
        for kw in general_keywords:
            if kw in name_lower:
                return "General Contractor"

        return "Construction"

    def parse_record(self, raw_record: Dict[str, Any]) -> ProspectRecord:
        """Convert raw record to ProspectRecord."""
        company_name = raw_record.get("company_name", "")

        # Parse address if available
        address_full = raw_record.get("registered_address", "") or ""
        address_parts = address_full.split(",") if address_full else []

        address = address_parts[0].strip() if len(address_parts) > 0 else ""
        city = address_parts[1].strip() if len(address_parts) > 1 else ""

        # Calculate years in business
        years_in_business = None
        inc_date = raw_record.get("incorporation_date")
        if inc_date:
            try:
                inc_year = int(str(inc_date)[:4])
                years_in_business = datetime.now().year - inc_year
            except (ValueError, TypeError):
                pass

        # Determine contractor type from name
        contractor_type = self._determine_contractor_type(company_name)

        return ProspectRecord(
            company_name=company_name,
            dba_name=raw_record.get("dba_name"),
            industry_id=raw_record.get("company_number") or raw_record.get("license_number"),
            phone=self.clean_phone_number(raw_record.get("phone")),
            email=raw_record.get("email"),
            website=raw_record.get("website"),
            address=address,
            city=city,
            state=raw_record.get("state", ""),
            zip_code=raw_record.get("zip_code", ""),
            mailing_address=None,
            mailing_city=None,
            mailing_state=None,
            mailing_zip=None,
            business_size_metric=raw_record.get("employee_count"),
            business_size_label="Employees",
            employee_count=raw_record.get("employee_count"),
            years_in_business=years_in_business,
            industry_data={
                "License Number": raw_record.get("license_number", ""),
                "Contractor Type": contractor_type,
                "License Status": raw_record.get("status", "Active"),
                "License Types": raw_record.get("license_types", ""),
                "Incorporation Date": raw_record.get("incorporation_date", ""),
                "Company Type": raw_record.get("company_type", ""),
                "Source": raw_record.get("source", ""),
            },
        )

    def get_scoring_rules(self) -> List[Dict[str, Any]]:
        """Return construction-specific scoring rules."""
        return [
            # High-value contractor types (equipment-intensive)
            {
                "name": "general_contractor",
                "field": "industry_data",
                "rule_type": "custom",
                "points": 25,
                "description": "General contractor (broad equipment needs)",
                "params": {"check_field": "Contractor Type", "check_contains": "General"},
            },
            {
                "name": "heavy_civil",
                "field": "industry_data",
                "rule_type": "custom",
                "points": 30,
                "description": "Heavy/civil contractor (expensive equipment)",
                "params": {"check_field": "Contractor Type", "check_contains": "Heavy"},
            },
            {
                "name": "electrical_contractor",
                "field": "industry_data",
                "rule_type": "custom",
                "points": 20,
                "description": "Electrical contractor",
                "params": {"check_field": "Contractor Type", "check_value": "Electrical"},
            },
            {
                "name": "hvac_contractor",
                "field": "industry_data",
                "rule_type": "custom",
                "points": 20,
                "description": "HVAC contractor (equipment purchases)",
                "params": {"check_field": "Contractor Type", "check_value": "HVAC"},
            },
            {
                "name": "concrete_contractor",
                "field": "industry_data",
                "rule_type": "custom",
                "points": 20,
                "description": "Concrete contractor (equipment-intensive)",
                "params": {"check_field": "Contractor Type", "check_contains": "Concrete"},
            },
            {
                "name": "roofing_contractor",
                "field": "industry_data",
                "rule_type": "custom",
                "points": 15,
                "description": "Roofing contractor",
                "params": {"check_field": "Contractor Type", "check_value": "Roofing"},
            },
            # Established businesses
            {
                "name": "established_10_plus",
                "field": "years_in_business",
                "rule_type": "range",
                "params": {"min": 10, "max": 100},
                "points": 20,
                "description": "Established 10+ years",
            },
            {
                "name": "established_5_9",
                "field": "years_in_business",
                "rule_type": "range",
                "params": {"min": 5, "max": 9},
                "points": 15,
                "description": "Established 5-9 years",
            },
            {
                "name": "established_2_4",
                "field": "years_in_business",
                "rule_type": "range",
                "params": {"min": 2, "max": 4},
                "points": 10,
                "description": "Established 2-4 years",
            },
            # Contact info
            {
                "name": "has_phone",
                "field": "phone",
                "rule_type": "presence",
                "points": 10,
                "description": "Phone number available",
            },
            {
                "name": "has_email",
                "field": "email",
                "rule_type": "presence",
                "points": 10,
                "description": "Email available",
            },
            {
                "name": "has_website",
                "field": "website",
                "rule_type": "presence",
                "points": 5,
                "description": "Website available",
            },
        ]


# Utility functions for direct lookups

def search_contractors(
    name: str,
    state: Optional[str] = None,
    contractor_type: Optional[str] = None,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    """
    Search for construction contractors by name.

    Args:
        name: Company name to search for
        state: Optional state filter
        contractor_type: Optional contractor type filter
        limit: Maximum results to return

    Returns:
        List of matching contractor records
    """
    results = []

    # Search OpenCorporates
    url = f"{OPENCORPORATES_API}/companies/search"
    params = {
        "q": name,
        "per_page": min(limit, 30),
    }

    if state:
        params["jurisdiction_code"] = f"us_{state.lower()}"

    try:
        response = requests.get(url, params=params, timeout=30)
        if response.status_code == 200:
            data = response.json()
            companies = data.get("results", {}).get("companies", [])

            for company_data in companies:
                company = company_data.get("company", {})
                results.append({
                    "company_name": company.get("name", ""),
                    "company_number": company.get("company_number", ""),
                    "jurisdiction": company.get("jurisdiction_code", ""),
                    "status": company.get("current_status", ""),
                    "incorporation_date": company.get("incorporation_date"),
                    "registered_address": company.get("registered_address_in_full", ""),
                })
    except Exception as e:
        print(f"Error searching for '{name}': {e}")

    return results[:limit]


def get_contractors_by_city(
    city: str,
    state: str,
    contractor_type: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Get construction contractors in a specific city.

    Args:
        city: City name
        state: State abbreviation
        contractor_type: Optional contractor type filter

    Returns:
        List of contractor records
    """
    results = []

    # Search with city in query
    search_query = f"construction {city}"

    url = f"{OPENCORPORATES_API}/companies/search"
    params = {
        "q": search_query,
        "jurisdiction_code": f"us_{state.lower()}",
        "current_status": "Active",
        "per_page": 50,
    }

    try:
        response = requests.get(url, params=params, timeout=30)
        if response.status_code == 200:
            data = response.json()
            companies = data.get("results", {}).get("companies", [])

            for company_data in companies:
                company = company_data.get("company", {})
                address = company.get("registered_address_in_full", "").lower()

                # Filter by city if mentioned in address
                if city.lower() in address:
                    results.append({
                        "company_name": company.get("name", ""),
                        "company_number": company.get("company_number", ""),
                        "status": company.get("current_status", ""),
                        "incorporation_date": company.get("incorporation_date"),
                        "address": company.get("registered_address_in_full", ""),
                        "city": city,
                        "state": state,
                    })
    except Exception as e:
        print(f"Error fetching contractors in {city}, {state}: {e}")

    return results
