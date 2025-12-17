"""
Health Department Filings Prospector
=====================================

This module provides prospect finding for food service establishments
(restaurants, bars, cafes, etc.) using public health department data.

Data Sources:
- Florida DBPR - Food Service Establishments
- Texas DSHS - Food Establishment Data
- NYC DOHMH - Restaurant Inspections
- Other state/local open data portals

These businesses file with health departments for permits and inspections,
providing verified business and owner information.
"""

import requests
import time
import re
from typing import Any, Dict, List, Optional
from datetime import datetime

from ..core.base import IndustryProspector, ProspectRecord
from ..core.scoring import ScoringRule, RuleType


# Data source API endpoints
# Florida Department of Business and Professional Regulation
FL_DBPR_URL = "https://data.florida.gov/resource/72nm-6w5s.json"

# Texas Food Establishments (data.texas.gov)
TX_DSHS_URL = "https://data.texas.gov/resource/ckj5-t27h.json"

# NYC Restaurant Inspections (data.cityofnewyork.us)
NYC_DOHMH_URL = "https://data.cityofnewyork.us/resource/43nn-pn8j.json"

# Chicago Food Inspections
CHICAGO_URL = "https://data.cityofchicago.org/resource/4ijn-s7e5.json"

# California (multiple counties via Socrata)
CA_ALAMEDA_URL = "https://data.acgov.org/resource/23qd-6tku.json"

# State/City data source configurations
DATA_SOURCES = {
    "FL": {
        "url": FL_DBPR_URL,
        "name": "Florida DBPR",
        "fields": {
            "business_name": "licensee_name",
            "dba_name": "dba_name",
            "license_number": "license_number",
            "license_type": "license_type",
            "address": "location_address",
            "city": "city",
            "state": "state",
            "zip": "zip_code",
            "county": "county",
            "status": "license_status",
            "expiration_date": "license_expiration_date",
            "phone": None,  # Not available in this dataset
        },
        "facility_type_field": "license_type",
        "restaurant_types": ["Food Service", "Food Service License", "Permanent Food Service"],
    },
    "TX": {
        "url": TX_DSHS_URL,
        "name": "Texas DSHS",
        "fields": {
            "business_name": "restaurant_name",
            "dba_name": None,
            "license_number": "inspection_id",
            "license_type": "restaurant_type",
            "address": "address",
            "city": "city",
            "state": None,  # Always TX
            "zip": "zip",
            "county": "county",
            "status": None,
            "expiration_date": None,
            "phone": None,
        },
        "facility_type_field": "restaurant_type",
        "restaurant_types": ["Restaurant", "Food Service", "Bar", "Tavern"],
    },
    "NYC": {
        "url": NYC_DOHMH_URL,
        "name": "NYC DOHMH",
        "fields": {
            "business_name": "dba",
            "dba_name": None,
            "license_number": "camis",
            "license_type": "cuisine_description",
            "address": "building",
            "street": "street",
            "city": "boro",
            "state": None,  # Always NY
            "zip": "zipcode",
            "county": "boro",
            "status": None,
            "expiration_date": None,
            "phone": "phone",
            "score": "score",
            "grade": "grade",
        },
        "facility_type_field": "cuisine_description",
        "restaurant_types": None,  # All are food service
    },
    "CHICAGO": {
        "url": CHICAGO_URL,
        "name": "Chicago CDPH",
        "fields": {
            "business_name": "dba_name",
            "dba_name": "aka_name",
            "license_number": "license_",
            "license_type": "facility_type",
            "address": "address",
            "city": "city",
            "state": "state",
            "zip": "zip",
            "county": None,
            "status": "results",
            "expiration_date": None,
            "phone": None,
        },
        "facility_type_field": "facility_type",
        "restaurant_types": ["Restaurant", "Bakery", "Bar", "Tavern", "Grocery Store", "Catering"],
    },
}


class HealthDeptProspector(IndustryProspector):
    """
    Prospector for food service establishments using health department data.

    Pulls restaurant, bar, and food service business data from public health
    department databases. These establishments must file with health departments
    for permits, providing verified business information.

    Configuration options:
        target_states: List of state abbreviations to search (FL, TX, NY, IL)
        facility_types: List of facility types to include (restaurant, bar, etc.)
        active_only: Only include businesses with active licenses
        max_records_per_source: Maximum records to fetch per data source
        include_cities: Include city-level data sources (NYC, Chicago)
        app_token: Optional Socrata app token for higher rate limits
    """

    DEFAULT_CONFIG = {
        "target_states": ["FL", "TX"],
        "facility_types": None,  # None = all food service types
        "active_only": True,
        "max_records_per_source": 10000,
        "include_cities": True,
        "app_token": None,
    }

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize the health department prospector.

        Args:
            config: Configuration dictionary. Missing keys will use defaults.
        """
        merged_config = {**self.DEFAULT_CONFIG, **(config or {})}
        super().__init__(merged_config)

    def get_industry_name(self) -> str:
        return "Health Dept Filings (Restaurants/Bars)"

    def _get_active_sources(self) -> List[str]:
        """Get list of data sources to query based on config."""
        sources = []

        for state in self.config["target_states"]:
            state_upper = state.upper()
            if state_upper in DATA_SOURCES:
                sources.append(state_upper)

        # Add city sources if enabled
        if self.config.get("include_cities", True):
            # NYC is part of NY state
            if "NY" in [s.upper() for s in self.config["target_states"]]:
                sources.append("NYC")
            # Chicago is part of IL state
            if "IL" in [s.upper() for s in self.config["target_states"]]:
                sources.append("CHICAGO")

        return list(set(sources))  # Deduplicate

    def _build_query_params(self, source_key: str, offset: int = 0) -> Dict[str, str]:
        """Build Socrata SoQL query parameters for a data source."""
        source = DATA_SOURCES[source_key]

        params = {
            "$limit": str(self.config["max_records_per_source"]),
            "$offset": str(offset),
        }

        # Add app token if provided
        if self.config.get("app_token"):
            params["$$app_token"] = self.config["app_token"]

        # Build where clause based on source specifics
        where_conditions = []

        # Filter by facility type if specified
        if source.get("restaurant_types") and source.get("facility_type_field"):
            type_field = source["facility_type_field"]
            types = source["restaurant_types"]
            type_conditions = [f"upper({type_field}) like upper('%{t}%')" for t in types]
            where_conditions.append(f"({' OR '.join(type_conditions)})")

        # Filter by active status if applicable
        if self.config.get("active_only"):
            status_field = source["fields"].get("status")
            if status_field and source_key == "FL":
                where_conditions.append(f"{status_field}='ACTIVE'")
            elif status_field and source_key == "CHICAGO":
                where_conditions.append(f"{status_field}='Pass'")

        if where_conditions:
            params["$where"] = " AND ".join(where_conditions)

        return params

    def _fetch_source_data(self, source_key: str, max_retries: int = 3) -> List[Dict[str, Any]]:
        """Fetch data from a single source."""
        source = DATA_SOURCES[source_key]
        all_records = []
        offset = 0

        print(f"  Fetching from {source['name']}...", end="", flush=True)

        while True:
            params = self._build_query_params(source_key, offset)

            for attempt in range(max_retries):
                try:
                    response = requests.get(
                        source["url"],
                        params=params,
                        timeout=60
                    )
                    response.raise_for_status()
                    data = response.json()

                    if not data:
                        print(f" {len(all_records)} records")
                        return all_records

                    # Tag records with source info
                    for record in data:
                        record["_source_key"] = source_key
                        record["_source_name"] = source["name"]

                    all_records.extend(data)

                    # If we got less than the limit, we have all records
                    if len(data) < self.config["max_records_per_source"]:
                        print(f" {len(all_records)} records")
                        return all_records

                    offset += self.config["max_records_per_source"]
                    time.sleep(0.5)  # Rate limiting
                    break

                except requests.exceptions.RequestException as e:
                    if attempt < max_retries - 1:
                        time.sleep(2 ** attempt)  # Exponential backoff
                    else:
                        print(f" ERROR: {e}")
                        return all_records

        return all_records

    def fetch_prospects(self) -> List[Dict[str, Any]]:
        """Fetch prospect data from all configured health department sources."""
        all_records = []

        sources = self._get_active_sources()

        print(f"\nFetching health department filings...")
        print(f"  Sources: {', '.join(sources)}")
        print()

        for source_key in sources:
            source_records = self._fetch_source_data(source_key)
            all_records.extend(source_records)
            time.sleep(1)  # Be nice to the API between sources

        print(f"\nTotal raw records: {len(all_records)}")
        return all_records

    @staticmethod
    def clean_phone_number(phone: Any) -> str:
        """Clean and format phone number."""
        if phone is None or phone == "":
            return ""
        # Remove all non-digits
        digits = re.sub(r"\D", "", str(phone))
        # Format as (XXX) XXX-XXXX if 10 digits
        if len(digits) == 10:
            return f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"
        elif len(digits) == 11 and digits[0] == "1":
            return f"({digits[1:4]}) {digits[4:7]}-{digits[7:]}"
        return str(phone) if phone else ""

    @staticmethod
    def clean_business_name(name: Any) -> str:
        """Clean and normalize business name."""
        if not name:
            return ""
        name = str(name).strip()
        # Title case if all caps
        if name.isupper():
            name = name.title()
        return name

    def parse_record(self, raw_record: Dict[str, Any]) -> ProspectRecord:
        """Convert raw health department record to ProspectRecord."""
        source_key = raw_record.get("_source_key", "FL")
        source = DATA_SOURCES.get(source_key, DATA_SOURCES["FL"])
        fields = source["fields"]

        # Extract fields using source-specific mapping
        business_name = self.clean_business_name(
            raw_record.get(fields.get("business_name", ""), "")
        )
        dba_name = raw_record.get(fields.get("dba_name", ""), None) if fields.get("dba_name") else None

        license_number = raw_record.get(fields.get("license_number", ""), "")
        license_type = raw_record.get(fields.get("license_type", ""), "")

        # Handle address - some sources have separate street field
        address = raw_record.get(fields.get("address", ""), "")
        if fields.get("street"):
            street = raw_record.get(fields.get("street", ""), "")
            if street and address:
                address = f"{address} {street}"
            elif street:
                address = street

        city = raw_record.get(fields.get("city", ""), "")

        # State - some sources don't have it, use source key
        state = raw_record.get(fields.get("state", ""), "") if fields.get("state") else None
        if not state:
            if source_key == "NYC":
                state = "NY"
            elif source_key == "CHICAGO":
                state = "IL"
            elif source_key == "TX":
                state = "TX"
            else:
                state = source_key if len(source_key) == 2 else ""

        zip_code = str(raw_record.get(fields.get("zip", ""), ""))
        if zip_code and len(zip_code) > 5:
            zip_code = zip_code[:5]

        county = raw_record.get(fields.get("county", ""), "") if fields.get("county") else None

        # Phone
        phone_field = fields.get("phone")
        phone = self.clean_phone_number(raw_record.get(phone_field, "")) if phone_field else ""

        # Status and expiration
        status = raw_record.get(fields.get("status", ""), "") if fields.get("status") else "Unknown"
        expiration = raw_record.get(fields.get("expiration_date", ""), "") if fields.get("expiration_date") else None

        # Health inspection score (NYC specific)
        inspection_score = raw_record.get(fields.get("score", ""), None) if fields.get("score") else None
        inspection_grade = raw_record.get(fields.get("grade", ""), None) if fields.get("grade") else None

        # Build industry data
        industry_data = {
            "License Number": license_number,
            "License Type": license_type,
            "License Status": status,
            "County": county or "",
            "Data Source": raw_record.get("_source_name", "Unknown"),
        }

        if expiration:
            industry_data["License Expiration"] = expiration
        if inspection_score:
            industry_data["Inspection Score"] = inspection_score
        if inspection_grade:
            industry_data["Inspection Grade"] = inspection_grade

        return ProspectRecord(
            company_name=business_name,
            dba_name=dba_name,
            industry_id=str(license_number) if license_number else None,
            phone=phone,
            address=address,
            city=city,
            state=state,
            zip_code=zip_code,
            business_size_label="Establishment",
            industry_data=industry_data,
        )

    def get_scoring_rules(self) -> List[Dict[str, Any]]:
        """Return health department prospect scoring rules."""
        return [
            # Contact info scoring
            {
                "name": "has_phone",
                "field": "phone",
                "rule_type": "presence",
                "points": 20,
                "description": "Phone number available",
            },
            # Active license bonus
            {
                "name": "active_license",
                "field": "industry_data",
                "rule_type": "custom",
                "points": 15,
                "description": "Has active license status",
                "params": {"check_field": "License Status", "check_value": "ACTIVE"},
            },
            # Full address bonus
            {
                "name": "has_full_address",
                "field": "address",
                "rule_type": "presence",
                "points": 10,
                "description": "Complete address available",
            },
            {
                "name": "has_city",
                "field": "city",
                "rule_type": "presence",
                "points": 5,
                "description": "City available",
            },
            {
                "name": "has_zip",
                "field": "zip_code",
                "rule_type": "presence",
                "points": 5,
                "description": "ZIP code available",
            },
            # Restaurant type bonuses (higher-revenue establishments)
            {
                "name": "is_restaurant",
                "field": "industry_data",
                "rule_type": "custom",
                "points": 15,
                "description": "Full-service restaurant (higher revenue potential)",
                "params": {"check_field": "License Type", "contains": ["restaurant", "food service"]},
            },
            {
                "name": "is_bar",
                "field": "industry_data",
                "rule_type": "custom",
                "points": 10,
                "description": "Bar/tavern establishment",
                "params": {"check_field": "License Type", "contains": ["bar", "tavern", "lounge"]},
            },
            # Good inspection score (NYC specific)
            {
                "name": "good_inspection",
                "field": "industry_data",
                "rule_type": "custom",
                "points": 10,
                "description": "Good inspection grade (A or B)",
                "params": {"check_field": "Inspection Grade", "check_values": ["A", "B"]},
            },
        ]


# Utility functions for direct lookups

def lookup_by_license(
    license_number: str,
    state: str = "FL",
    app_token: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """
    Look up a specific establishment by license number.

    Args:
        license_number: License number to look up
        state: State abbreviation for data source
        app_token: Optional Socrata app token

    Returns:
        Establishment data dictionary or None if not found
    """
    state_upper = state.upper()
    if state_upper not in DATA_SOURCES:
        print(f"No data source available for state: {state}")
        return None

    source = DATA_SOURCES[state_upper]
    license_field = source["fields"].get("license_number")

    if not license_field:
        print(f"License lookup not supported for {source['name']}")
        return None

    params = {
        "$where": f"{license_field}='{license_number}'",
        "$limit": "1",
    }
    if app_token:
        params["$$app_token"] = app_token

    try:
        response = requests.get(source["url"], params=params, timeout=30)
        response.raise_for_status()
        data = response.json()
        if data:
            record = data[0]
            fields = source["fields"]
            return {
                "license_number": record.get(fields.get("license_number", "")),
                "business_name": record.get(fields.get("business_name", "")),
                "dba_name": record.get(fields.get("dba_name", "")) if fields.get("dba_name") else None,
                "address": record.get(fields.get("address", "")),
                "city": record.get(fields.get("city", "")),
                "state": state_upper,
                "zip": record.get(fields.get("zip", "")),
                "license_type": record.get(fields.get("license_type", "")),
                "status": record.get(fields.get("status", "")) if fields.get("status") else "Unknown",
                "source": source["name"],
            }
        return None
    except Exception as e:
        print(f"Error looking up license {license_number}: {e}")
        return None


def search_by_name(
    business_name: str,
    state: str = "FL",
    city: Optional[str] = None,
    limit: int = 100,
    app_token: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Search for establishments by name (partial match).

    Args:
        business_name: Business name to search for
        state: State abbreviation for data source
        city: Optional city filter
        limit: Maximum results to return
        app_token: Optional Socrata app token

    Returns:
        List of matching establishment records
    """
    state_upper = state.upper()
    if state_upper not in DATA_SOURCES:
        print(f"No data source available for state: {state}")
        return []

    source = DATA_SOURCES[state_upper]
    name_field = source["fields"].get("business_name")

    if not name_field:
        return []

    where_clause = f"upper({name_field}) like upper('%{business_name}%')"

    if city:
        city_field = source["fields"].get("city")
        if city_field:
            where_clause += f" AND upper({city_field}) = upper('{city}')"

    params = {
        "$where": where_clause,
        "$limit": str(limit),
    }
    if app_token:
        params["$$app_token"] = app_token

    try:
        response = requests.get(source["url"], params=params, timeout=30)
        response.raise_for_status()
        records = response.json()

        fields = source["fields"]
        return [
            {
                "license_number": r.get(fields.get("license_number", "")),
                "business_name": r.get(fields.get("business_name", "")),
                "address": r.get(fields.get("address", "")),
                "city": r.get(fields.get("city", "")),
                "state": state_upper,
                "zip": r.get(fields.get("zip", "")),
                "license_type": r.get(fields.get("license_type", "")),
            }
            for r in records
        ]
    except Exception as e:
        print(f"Error searching for '{business_name}': {e}")
        return []


def get_establishments_by_city(
    city: str,
    state: str,
    facility_type: Optional[str] = None,
    limit: int = 1000,
    app_token: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Get all food establishments in a specific city.

    Args:
        city: City name
        state: State abbreviation
        facility_type: Optional filter (e.g., 'restaurant', 'bar')
        limit: Maximum results
        app_token: Optional Socrata app token

    Returns:
        List of establishment records
    """
    state_upper = state.upper()
    if state_upper not in DATA_SOURCES:
        print(f"No data source available for state: {state}")
        return []

    source = DATA_SOURCES[state_upper]
    city_field = source["fields"].get("city")

    if not city_field:
        return []

    where_clause = f"upper({city_field}) = upper('{city}')"

    if facility_type:
        type_field = source.get("facility_type_field")
        if type_field:
            where_clause += f" AND upper({type_field}) like upper('%{facility_type}%')"

    params = {
        "$where": where_clause,
        "$limit": str(limit),
    }
    if app_token:
        params["$$app_token"] = app_token

    try:
        response = requests.get(source["url"], params=params, timeout=30)
        response.raise_for_status()
        records = response.json()

        fields = source["fields"]
        return [
            {
                "license_number": r.get(fields.get("license_number", "")),
                "business_name": r.get(fields.get("business_name", "")),
                "address": r.get(fields.get("address", "")),
                "city": r.get(fields.get("city", "")),
                "state": state_upper,
                "zip": r.get(fields.get("zip", "")),
                "license_type": r.get(fields.get("license_type", "")),
                "status": r.get(fields.get("status", "")) if fields.get("status") else "Unknown",
            }
            for r in records
        ]
    except Exception as e:
        print(f"Error fetching establishments in {city}, {state}: {e}")
        return []


def get_county_establishments(
    county: str,
    state: str = "FL",
    limit: int = 5000,
    app_token: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Get all food establishments in a specific county.

    Args:
        county: County name
        state: State abbreviation
        limit: Maximum results
        app_token: Optional Socrata app token

    Returns:
        List of establishment records
    """
    state_upper = state.upper()
    if state_upper not in DATA_SOURCES:
        print(f"No data source available for state: {state}")
        return []

    source = DATA_SOURCES[state_upper]
    county_field = source["fields"].get("county")

    if not county_field:
        print(f"County lookup not supported for {source['name']}")
        return []

    params = {
        "$where": f"upper({county_field}) = upper('{county}')",
        "$limit": str(limit),
    }
    if app_token:
        params["$$app_token"] = app_token

    try:
        response = requests.get(source["url"], params=params, timeout=30)
        response.raise_for_status()
        records = response.json()

        fields = source["fields"]
        return [
            {
                "license_number": r.get(fields.get("license_number", "")),
                "business_name": r.get(fields.get("business_name", "")),
                "address": r.get(fields.get("address", "")),
                "city": r.get(fields.get("city", "")),
                "county": r.get(county_field, ""),
                "state": state_upper,
                "zip": r.get(fields.get("zip", "")),
                "license_type": r.get(fields.get("license_type", "")),
                "status": r.get(fields.get("status", "")) if fields.get("status") else "Unknown",
            }
            for r in records
        ]
    except Exception as e:
        print(f"Error fetching establishments in {county} County, {state}: {e}")
        return []
