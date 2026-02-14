"""
FMCSA Trucking Industry Prospector
==================================

This module provides prospect finding for the trucking industry using
the FMCSA (Federal Motor Carrier Safety Administration) public database.

Data Source: DOT Open Data Portal (data.transportation.gov)
Dataset: Company Census File
API: Socrata Open Data API (SODA)

No API key required for basic access (throttled to ~1000 requests/hour without key).
With an app token, rate limits are much higher.
"""

import requests
import time
import re
from typing import Any, Dict, List, Optional
from datetime import datetime

from ..core.base import IndustryProspector, ProspectRecord
from ..core.scoring import ScoringRule, RuleType


# Socrata API endpoints
FMCSA_CENSUS_URL = "https://data.transportation.gov/resource/az4n-8mr2.json"
FMCSA_SMS_URL = "https://data.transportation.gov/resource/vfhy-96ib.json"


class TruckingProspector(IndustryProspector):
    """
    Prospector for the trucking industry using FMCSA data.

    Pulls motor carrier data from the DOT Open Data Portal and filters
    it based on configurable criteria like fleet size, location, and
    operating status.

    Configuration options:
        target_states: List of state abbreviations to search
        min_power_units: Minimum number of trucks
        max_power_units: Maximum number of trucks
        carrier_operation: List of operation types (A=Interstate, B=Intrastate Hazmat, C=Intrastate Non-Hazmat)
        entity_types: List of entity types (C=Carrier, B=Broker, F=Freight Forwarder)
        max_records_per_state: Maximum records to fetch per state
        app_token: Optional Socrata app token for higher rate limits
    """

    DEFAULT_CONFIG = {
        "target_states": ["FL", "GA", "IL", "TX", "CA", "NC", "TN", "OH", "PA", "NJ", "NY"],
        "min_power_units": 1,
        "max_power_units": 50,
        "carrier_operation": ["A", "B"],  # Interstate carriers
        "entity_types": ["C"],  # Carriers only (not brokers)
        "max_records_per_state": 10000,
        "app_token": None,
    }

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize the trucking prospector.

        Args:
            config: Configuration dictionary. Missing keys will use defaults.
        """
        merged_config = {**self.DEFAULT_CONFIG, **(config or {})}
        super().__init__(merged_config)
        self.api_url = FMCSA_CENSUS_URL

    def get_industry_name(self) -> str:
        return "Trucking (FMCSA)"

    def _build_query_params(self, state: str, offset: int = 0) -> Dict[str, str]:
        """Build Socrata SoQL query parameters."""
        where_conditions = [
            f"phy_state='{state}'",
            f"power_units::number>={self.config['min_power_units']}",
            f"power_units::number<={self.config['max_power_units']}",
            "status_code='A'",
        ]

        params = {
            "$where": " AND ".join(where_conditions),
            "$limit": str(self.config["max_records_per_state"]),
            "$offset": str(offset),
            "$order": "power_units::number DESC",
        }

        # Add app token if provided
        if self.config.get("app_token"):
            params["$$app_token"] = self.config["app_token"]

        return params

    def _fetch_state_data(self, state: str, max_retries: int = 3) -> List[Dict[str, Any]]:
        """Fetch data for a single state."""
        all_records = []
        offset = 0

        print(f"  Fetching {state}...", end="", flush=True)

        while True:
            params = self._build_query_params(state, offset)

            for attempt in range(max_retries):
                try:
                    response = requests.get(
                        self.api_url,
                        params=params,
                        timeout=60
                    )
                    response.raise_for_status()
                    data = response.json()

                    if not data:
                        print(f" {len(all_records)} records")
                        return all_records

                    all_records.extend(data)

                    # If we got less than the limit, we have all records
                    if len(data) < self.config["max_records_per_state"]:
                        print(f" {len(all_records)} records")
                        return all_records

                    offset += self.config["max_records_per_state"]
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
        """Fetch prospect data from FMCSA for all target states."""
        all_records = []

        print(f"\nFetching trucking prospects from FMCSA...")
        print(f"  States: {', '.join(self.config['target_states'])}")
        print(f"  Fleet size: {self.config['min_power_units']}-{self.config['max_power_units']} trucks")
        print()

        for state in self.config["target_states"]:
            state_records = self._fetch_state_data(state)
            all_records.extend(state_records)
            time.sleep(1)  # Be nice to the API between states

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

    def parse_record(self, raw_record: Dict[str, Any]) -> ProspectRecord:
        """Convert raw FMCSA record to ProspectRecord."""
        # Parse power units
        power_units = None
        try:
            power_units = int(raw_record.get("power_units", 0) or 0)
        except (ValueError, TypeError):
            power_units = 0

        # Parse drivers
        drivers = None
        try:
            drivers = int(raw_record.get("total_drivers", 0) or 0)
        except (ValueError, TypeError):
            drivers = None

        # Estimate years in business from MCS-150 date
        years_in_business = None
        mcs150_date = raw_record.get("mcs150_date")
        if mcs150_date:
            try:
                if len(mcs150_date) >= 10:
                    if "-" in mcs150_date:
                        dt = datetime.strptime(mcs150_date[:10], "%Y-%m-%d")
                    elif "/" in mcs150_date:
                        dt = datetime.strptime(mcs150_date[:10], "%m/%d/%Y")
                    else:
                        dt = None
                    if dt:
                        years_in_business = max(1, (datetime.now() - dt).days / 365 + 2)
            except (ValueError, TypeError):
                pass

        return ProspectRecord(
            company_name=raw_record.get("legal_name", ""),
            dba_name=raw_record.get("dba_name"),
            industry_id=raw_record.get("dot_number"),
            phone=self.clean_phone_number(raw_record.get("phone")),
            email=raw_record.get("email_address"),
            address=raw_record.get("phy_street"),
            city=raw_record.get("phy_city"),
            state=raw_record.get("phy_state"),
            zip_code=raw_record.get("phy_zip"),
            mailing_address=raw_record.get("carrier_mailing_street"),
            mailing_city=raw_record.get("carrier_mailing_city"),
            mailing_state=raw_record.get("carrier_mailing_state"),
            mailing_zip=raw_record.get("carrier_mailing_zip"),
            business_size_metric=power_units,
            business_size_label="Trucks",
            employee_count=drivers,
            years_in_business=years_in_business,
            industry_data={
                "DOT Number": raw_record.get("dot_number"),
                "Drivers": drivers,
                "Operation Type": raw_record.get("carrier_operation"),
                "Status": "ACTIVE" if raw_record.get("status_code") == "A" else raw_record.get("status_code"),
                "Last Updated": raw_record.get("mcs150_date"),
            },
        )

    def get_scoring_rules(self) -> List[Dict[str, Any]]:
        """Return trucking-specific scoring rules."""
        return [
            # Fleet size scoring
            {
                "name": "fleet_sweet_spot",
                "field": "business_size_metric",
                "rule_type": "range",
                "params": {"min": 5, "max": 20},
                "points": 30,
                "description": "Sweet spot for financing deals",
            },
            {
                "name": "fleet_small_established",
                "field": "business_size_metric",
                "rule_type": "range",
                "params": {"min": 2, "max": 4},
                "points": 20,
                "description": "Small but established",
            },
            {
                "name": "fleet_medium",
                "field": "business_size_metric",
                "rule_type": "range",
                "params": {"min": 21, "max": 35},
                "points": 15,
                "description": "Medium fleet",
            },
            {
                "name": "fleet_owner_operator",
                "field": "business_size_metric",
                "rule_type": "range",
                "params": {"min": 1, "max": 1},
                "points": 5,
                "description": "Owner-operator",
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
                "points": 15,
                "description": "Email address available",
            },
            # Interstate carrier bonus
            {
                "name": "interstate_carrier",
                "field": "industry_data",
                "rule_type": "custom",
                "points": 10,
                "description": "Interstate carrier (broader operations)",
                "params": {"check_field": "Operation Type", "check_value": "A"},
            },
        ]


# Utility functions for direct lookups

def lookup_by_dot(dot_number: str, app_token: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """
    Look up a specific company by DOT number.

    Args:
        dot_number: USDOT number to look up
        app_token: Optional Socrata app token

    Returns:
        Company data dictionary or None if not found
    """
    params = {
        "$where": f"dot_number = '{dot_number}'",
        "$limit": "1",
    }
    if app_token:
        params["$$app_token"] = app_token

    try:
        response = requests.get(FMCSA_CENSUS_URL, params=params, timeout=30)
        response.raise_for_status()
        data = response.json()
        if data:
            record = data[0]
            return {
                "dot_number": record.get("dot_number"),
                "legal_name": record.get("legal_name"),
                "dba_name": record.get("dba_name"),
                "phone": record.get("phone"),
                "email": record.get("email_address"),
                "address": record.get("phy_street"),
                "city": record.get("phy_city"),
                "state": record.get("phy_state"),
                "zip": record.get("phy_zip"),
                "power_units": record.get("power_units"),
                "total_drivers": record.get("total_drivers"),
                "carrier_operation": record.get("carrier_operation"),
                "status": "ACTIVE" if record.get("status_code") == "A" else record.get("status_code"),
                "mcs150_date": record.get("mcs150_date"),
            }
        return None
    except Exception as e:
        print(f"Error looking up DOT {dot_number}: {e}")
        return None


def search_by_name(
    company_name: str,
    state: Optional[str] = None,
    limit: int = 100,
    app_token: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Search for companies by name (partial match).

    Args:
        company_name: Company name to search for
        state: Optional state filter
        limit: Maximum results to return
        app_token: Optional Socrata app token

    Returns:
        List of matching company records
    """
    where_clause = f"upper(legal_name) like upper('%{company_name}%')"
    if state:
        where_clause += f" AND phy_state = '{state}'"

    params = {
        "$where": where_clause,
        "$limit": str(limit),
        "$order": "power_units DESC",
    }
    if app_token:
        params["$$app_token"] = app_token

    try:
        response = requests.get(FMCSA_CENSUS_URL, params=params, timeout=30)
        response.raise_for_status()
        records = response.json()
        return [
            {
                "dot_number": r.get("dot_number"),
                "legal_name": r.get("legal_name"),
                "phone": r.get("phone"),
                "email": r.get("email_address"),
                "city": r.get("phy_city"),
                "state": r.get("phy_state"),
                "power_units": r.get("power_units"),
                "total_drivers": r.get("total_drivers"),
            }
            for r in records
        ]
    except Exception as e:
        print(f"Error searching for '{company_name}': {e}")
        return []


def get_carriers_by_city(
    city: str,
    state: str,
    min_trucks: int = 1,
    max_trucks: int = 50,
    app_token: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Get carriers in a specific city.

    Args:
        city: City name
        state: State abbreviation
        min_trucks: Minimum fleet size
        max_trucks: Maximum fleet size
        app_token: Optional Socrata app token

    Returns:
        List of carrier records
    """
    where_clause = (
        f"upper(phy_city) = upper('{city}') AND "
        f"phy_state = '{state}' AND "
        f"power_units::number >= {min_trucks} AND "
        f"power_units::number <= {max_trucks} AND "
        f"status_code = 'A'"
    )

    params = {
        "$where": where_clause,
        "$limit": "1000",
        "$order": "power_units::number DESC",
    }
    if app_token:
        params["$$app_token"] = app_token

    try:
        response = requests.get(FMCSA_CENSUS_URL, params=params, timeout=30)
        response.raise_for_status()
        records = response.json()
        return [
            {
                "dot_number": r.get("dot_number"),
                "legal_name": r.get("legal_name"),
                "phone": r.get("phone"),
                "email": r.get("email_address"),
                "address": r.get("phy_street"),
                "city": r.get("phy_city"),
                "state": r.get("phy_state"),
                "zip": r.get("phy_zip"),
                "power_units": r.get("power_units"),
                "total_drivers": r.get("total_drivers"),
            }
            for r in records
        ]
    except Exception as e:
        print(f"Error fetching carriers in {city}, {state}: {e}")
        return []


class TruckingEnricher:
    """
    Enricher for trucking industry leads using FMCSA data.

    Takes existing lead lists and enriches them with official FMCSA data
    including DOT verification, fleet size, and contact information.
    """

    def __init__(self, app_token: Optional[str] = None, match_threshold: float = 0.7):
        """
        Initialize the trucking enricher.

        Args:
            app_token: Optional Socrata app token for higher rate limits
            match_threshold: Minimum similarity score for name matching
        """
        from ..core.enricher import LeadEnricher

        self.app_token = app_token
        self.enricher = LeadEnricher(
            lookup_func=lambda dot: lookup_by_dot(dot, app_token),
            name_search_func=lambda name, state: search_by_name(name, state, app_token=app_token),
            match_threshold=match_threshold,
        )

    def enrich_file(
        self,
        input_file: str,
        output_file: str,
        dot_column: Optional[str] = None,
        name_column: Optional[str] = None,
        state_column: Optional[str] = None,
    ) -> None:
        """
        Enrich a CSV file of leads with FMCSA data.

        Args:
            input_file: Path to input CSV file
            output_file: Path to output CSV file
            dot_column: Column name for DOT number (auto-detected if None)
            name_column: Column name for company name (auto-detected if None)
            state_column: Column name for state (auto-detected if None)
        """
        import pandas as pd

        print(f"\nLoading {input_file}...")
        df = pd.read_csv(input_file)
        print(f"Found {len(df)} records")

        # Auto-detect columns if not specified
        detected = self.enricher.auto_detect_columns(df)
        dot_column = dot_column or detected["id_column"]
        name_column = name_column or detected["name_column"]
        state_column = state_column or detected["state_column"]

        print(f"\nDetected columns:")
        print(f"  DOT Number: {dot_column or 'Not found'}")
        print(f"  Company Name: {name_column or 'Not found'}")
        print(f"  State: {state_column or 'Not found'}")

        if not dot_column and not (name_column and state_column):
            print("\nError: Need either a DOT number column, or both Company Name and State columns")
            return

        # Enrich the data
        print("\nEnriching records...")

        def progress(current, total):
            if current % 10 == 0 or current == total:
                print(f"  Processing {current}/{total}...", end="\r")

        result_df = self.enricher.enrich_dataframe(
            df,
            id_column=dot_column,
            name_column=name_column,
            state_column=state_column,
            prefix="FMCSA_",
            progress_callback=progress,
        )

        # Save results
        result_df.to_csv(output_file, index=False)
        print(f"\nOutput saved to: {output_file}")
