"""
Aviation Industry Prospector (FAA Aircraft Registry)
=====================================================

This module provides prospect finding for the aviation industry using
the FAA Aircraft Registry database.

Data Source: FAA Releasable Aircraft Database
URL: https://www.faa.gov/licenses_certificates/aircraft_certification/aircraft_registry/releasable_aircraft_download
API: N-Number Inquiry (https://registry.faa.gov/aircraftinquiry/)

The FAA provides downloadable CSV files updated monthly with all registered aircraft.
This prospector can use both the downloadable files and the web inquiry API.
"""

import requests
import time
import re
import zipfile
import io
import csv
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime
from pathlib import Path

from ..core.base import IndustryProspector, ProspectRecord
from ..core.scoring import ScoringRule, RuleType


# FAA data file URLs
FAA_REGISTRY_BASE = "https://registry.faa.gov"
FAA_DATA_URL = "https://registry.faa.gov/database/ReleasableAircraft.zip"
FAA_INQUIRY_URL = "https://registry.faa.gov/aircraftinquiry/Search/NNumberResult"

# Aircraft type codes that indicate high-value prospects
HIGH_VALUE_AIRCRAFT_TYPES = {
    # Fixed wing multi-engine (business/charter)
    "4": "Fixed Wing Multi-Engine",
    "5": "Rotorcraft",  # Helicopters
    "6": "Glider",
    "7": "Lighter Than Air",
    "8": "Powered Parachute",
    "9": "Weight Shift Control",
}

# Engine type codes
ENGINE_TYPES = {
    "0": "None",
    "1": "Reciprocating",
    "2": "Turbo-prop",
    "3": "Turbo-shaft",
    "4": "Turbo-jet",
    "5": "Turbo-fan",
    "6": "Ramjet",
    "7": "2 Cycle",
    "8": "4 Cycle",
    "9": "Unknown",
    "10": "Electric",
    "11": "Rotary",
}

# Registrant type codes (best financing prospects)
REGISTRANT_TYPES = {
    "1": "Individual",
    "2": "Partnership",
    "3": "Corporation",
    "4": "Co-Owned",
    "5": "Government",
    "7": "LLC",
    "8": "Non-Citizen Corporation",
    "9": "Non-Citizen Co-Owned",
}


class AviationProspector(IndustryProspector):
    """
    Prospector for the aviation industry using FAA Aircraft Registry.

    Pulls aircraft registration data from the FAA database and filters
    based on aircraft type, owner type, and location.

    Configuration options:
        target_states: List of state abbreviations to search
        aircraft_types: Types of aircraft to include (1-9)
        owner_types: Types of owners to include (1,2,3,7 = businesses)
        min_aircraft: Minimum aircraft count per owner (for fleet operators)
        max_aircraft: Maximum aircraft count per owner
        engine_types: Engine types to filter (2-5 = turbine = high value)
        use_cached_data: Use locally cached FAA data file
        data_file_path: Path to cached FAA data file
    """

    DEFAULT_CONFIG = {
        "target_states": ["FL", "TX", "CA", "AZ", "GA", "NC", "TN", "CO", "NV", "WA"],
        "aircraft_types": ["4", "5"],  # Multi-engine and rotorcraft
        "owner_types": ["3", "7", "2"],  # Corporation, LLC, Partnership
        "min_aircraft": 1,
        "max_aircraft": 100,
        "engine_types": None,  # All types if None
        "use_cached_data": False,
        "data_file_path": None,
        "limit_per_state": 500,
    }

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize the aviation prospector.

        Args:
            config: Configuration dictionary. Missing keys will use defaults.
        """
        merged_config = {**self.DEFAULT_CONFIG, **(config or {})}
        super().__init__(merged_config)
        self._aircraft_data = None
        self._owner_counts = {}

    def get_industry_name(self) -> str:
        return "Aviation (FAA Registry)"

    def _download_faa_data(self) -> Optional[Dict[str, List[Dict]]]:
        """
        Download and parse the FAA releasable aircraft database.

        Returns:
            Dictionary with 'master' and 'reserved' aircraft records
        """
        print("  Downloading FAA aircraft database...", end="", flush=True)

        try:
            response = requests.get(FAA_DATA_URL, timeout=120, stream=True)
            response.raise_for_status()

            # Extract ZIP file in memory
            with zipfile.ZipFile(io.BytesIO(response.content)) as zf:
                # The ZIP contains several files:
                # - MASTER.txt: Main aircraft registrations
                # - ACFTREF.txt: Aircraft reference data
                # - ENGINE.txt: Engine reference data
                # - DEALER.txt: Dealer registrations
                # - RESERVED.txt: Reserved N-numbers

                data = {"master": [], "acftref": {}, "engine": {}}

                # Parse MASTER.txt (main registrations)
                if "MASTER.txt" in zf.namelist():
                    with zf.open("MASTER.txt") as f:
                        content = io.TextIOWrapper(f, encoding="latin-1")
                        reader = csv.reader(content)
                        headers = next(reader)  # Skip header
                        headers = [h.strip() for h in headers]

                        for row in reader:
                            if len(row) >= 20:
                                record = dict(zip(headers, [v.strip() for v in row]))
                                data["master"].append(record)

                # Parse ACFTREF.txt for aircraft model info
                if "ACFTREF.txt" in zf.namelist():
                    with zf.open("ACFTREF.txt") as f:
                        content = io.TextIOWrapper(f, encoding="latin-1")
                        reader = csv.reader(content)
                        headers = next(reader)
                        headers = [h.strip() for h in headers]

                        for row in reader:
                            if len(row) >= 5:
                                record = dict(zip(headers, [v.strip() for v in row]))
                                code = record.get("CODE", "")
                                if code:
                                    data["acftref"][code] = record

                print(f" {len(data['master'])} aircraft records loaded")
                return data

        except requests.exceptions.RequestException as e:
            print(f" ERROR: {e}")
            return None
        except zipfile.BadZipFile as e:
            print(f" ERROR: Invalid ZIP file - {e}")
            return None

    def _load_cached_data(self, filepath: str) -> Optional[Dict[str, List[Dict]]]:
        """Load FAA data from a cached local file."""
        print(f"  Loading cached data from {filepath}...", end="", flush=True)

        try:
            data = {"master": [], "acftref": {}}

            with open(filepath, "r", encoding="latin-1") as f:
                reader = csv.reader(f)
                headers = next(reader)
                headers = [h.strip() for h in headers]

                for row in reader:
                    if len(row) >= 20:
                        record = dict(zip(headers, [v.strip() for v in row]))
                        data["master"].append(record)

            print(f" {len(data['master'])} records loaded")
            return data

        except Exception as e:
            print(f" ERROR: {e}")
            return None

    def _fetch_by_n_number(self, n_number: str) -> Optional[Dict[str, Any]]:
        """
        Fetch a single aircraft by N-number using the FAA inquiry API.

        This is a web scraping approach for individual lookups.
        """
        url = f"{FAA_INQUIRY_URL}"
        params = {"NNumbertxt": n_number}

        try:
            response = requests.get(url, params=params, timeout=30)
            response.raise_for_status()

            # Parse the response HTML (simplified)
            # In production, you'd use BeautifulSoup for proper parsing
            if "N-Number" in response.text and "not found" not in response.text.lower():
                # Aircraft found - would need HTML parsing to extract details
                return {"n_number": n_number, "found": True}

            return None

        except Exception as e:
            print(f"Error looking up N{n_number}: {e}")
            return None

    def _count_owner_aircraft(self, data: Dict[str, List[Dict]]) -> Dict[str, int]:
        """Count aircraft per owner for fleet size filtering."""
        owner_counts = {}

        for record in data.get("master", []):
            # Create owner key from name and address
            owner_key = (
                record.get("NAME", "").upper().strip(),
                record.get("STATE", "").upper().strip(),
            )
            if owner_key[0]:  # Has a name
                owner_counts[owner_key] = owner_counts.get(owner_key, 0) + 1

        return owner_counts

    def _filter_records(self, data: Dict[str, List[Dict]]) -> List[Dict[str, Any]]:
        """Filter FAA records based on configuration."""
        filtered = []

        target_states = [s.upper() for s in self.config["target_states"]]
        aircraft_types = self.config.get("aircraft_types")
        owner_types = self.config.get("owner_types")
        engine_types = self.config.get("engine_types")

        # Count aircraft per owner for fleet filtering
        self._owner_counts = self._count_owner_aircraft(data)

        for record in data.get("master", []):
            state = record.get("STATE", "").upper().strip()

            # Filter by state
            if state not in target_states:
                continue

            # Filter by aircraft type
            if aircraft_types:
                acft_type = record.get("TYPE AIRCRAFT", "")
                if acft_type not in aircraft_types:
                    continue

            # Filter by owner type
            if owner_types:
                owner_type = record.get("TYPE REGISTRANT", "")
                if owner_type not in owner_types:
                    continue

            # Filter by engine type (turbine = high value)
            if engine_types:
                eng_type = record.get("TYPE ENGINE", "")
                if eng_type not in engine_types:
                    continue

            # Filter by fleet size
            owner_key = (
                record.get("NAME", "").upper().strip(),
                state,
            )
            fleet_size = self._owner_counts.get(owner_key, 1)

            if fleet_size < self.config.get("min_aircraft", 1):
                continue
            if fleet_size > self.config.get("max_aircraft", 100):
                continue

            # Add fleet size to record
            record["_fleet_size"] = fleet_size

            filtered.append(record)

        return filtered

    def _aggregate_by_owner(self, records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Aggregate records by owner to create prospect records."""
        owners = {}

        for record in records:
            owner_key = (
                record.get("NAME", "").upper().strip(),
                record.get("STATE", "").upper().strip(),
            )

            if owner_key[0]:  # Has a name
                if owner_key not in owners:
                    owners[owner_key] = {
                        "name": record.get("NAME", ""),
                        "street": record.get("STREET", ""),
                        "street2": record.get("STREET2", ""),
                        "city": record.get("CITY", ""),
                        "state": record.get("STATE", ""),
                        "zip_code": record.get("ZIP CODE", ""),
                        "region": record.get("REGION", ""),
                        "type_registrant": record.get("TYPE REGISTRANT", ""),
                        "aircraft": [],
                        "aircraft_count": 0,
                    }

                # Add aircraft to owner's fleet
                aircraft_info = {
                    "n_number": record.get("N-NUMBER", ""),
                    "serial_number": record.get("SERIAL NUMBER", ""),
                    "mfr_mdl_code": record.get("MFR MDL CODE", ""),
                    "year_mfr": record.get("YEAR MFR", ""),
                    "type_aircraft": record.get("TYPE AIRCRAFT", ""),
                    "type_engine": record.get("TYPE ENGINE", ""),
                    "cert_issue_date": record.get("CERT ISSUE DATE", ""),
                }
                owners[owner_key]["aircraft"].append(aircraft_info)
                owners[owner_key]["aircraft_count"] += 1

        return list(owners.values())

    def fetch_prospects(self) -> List[Dict[str, Any]]:
        """Fetch prospect data from FAA Registry."""
        print(f"\nFetching aviation prospects from FAA Registry...")
        print(f"  States: {', '.join(self.config['target_states'])}")
        print(f"  Owner types: {', '.join(self.config.get('owner_types', ['All']))}")
        print()

        # Load data (download or use cache)
        if self.config.get("use_cached_data") and self.config.get("data_file_path"):
            data = self._load_cached_data(self.config["data_file_path"])
        else:
            data = self._download_faa_data()

        if not data:
            print("  Failed to load FAA data")
            return []

        # Filter and aggregate
        print("  Filtering records...", end="", flush=True)
        filtered = self._filter_records(data)
        print(f" {len(filtered)} matching aircraft")

        print("  Aggregating by owner...", end="", flush=True)
        prospects = self._aggregate_by_owner(filtered)
        print(f" {len(prospects)} unique owners")

        # Limit per state
        state_counts = {}
        limited_prospects = []

        for prospect in prospects:
            state = prospect.get("state", "")
            state_counts[state] = state_counts.get(state, 0) + 1

            if state_counts[state] <= self.config.get("limit_per_state", 500):
                limited_prospects.append(prospect)

        print(f"\nTotal prospects: {len(limited_prospects)}")
        return limited_prospects

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

    def parse_record(self, raw_record: Dict[str, Any]) -> ProspectRecord:
        """Convert raw FAA record to ProspectRecord."""
        # Get owner type description
        type_reg = raw_record.get("type_registrant", "")
        owner_type = REGISTRANT_TYPES.get(type_reg, "Unknown")

        # Build address
        street = raw_record.get("street", "")
        street2 = raw_record.get("street2", "")
        address = f"{street} {street2}".strip() if street2 else street

        # Get aircraft details
        aircraft_list = raw_record.get("aircraft", [])
        aircraft_count = raw_record.get("aircraft_count", len(aircraft_list))

        # Get primary aircraft info (first/largest)
        primary_aircraft = aircraft_list[0] if aircraft_list else {}

        # Determine aircraft types in fleet
        aircraft_types_in_fleet = set()
        engine_types_in_fleet = set()
        newest_year = 0

        for acft in aircraft_list:
            acft_type = HIGH_VALUE_AIRCRAFT_TYPES.get(
                acft.get("type_aircraft", ""),
                "Unknown"
            )
            aircraft_types_in_fleet.add(acft_type)

            eng_type = ENGINE_TYPES.get(acft.get("type_engine", ""), "Unknown")
            engine_types_in_fleet.add(eng_type)

            try:
                year = int(acft.get("year_mfr", 0) or 0)
                if year > newest_year:
                    newest_year = year
            except (ValueError, TypeError):
                pass

        # Calculate years in business (from oldest cert date)
        years_in_business = None
        oldest_cert = None
        for acft in aircraft_list:
            cert_date = acft.get("cert_issue_date", "")
            if cert_date and (not oldest_cert or cert_date < oldest_cert):
                oldest_cert = cert_date

        if oldest_cert:
            try:
                cert_year = int(oldest_cert[:4])
                years_in_business = datetime.now().year - cert_year
            except (ValueError, IndexError):
                pass

        # Build N-numbers list
        n_numbers = [f"N{a.get('n_number', '')}" for a in aircraft_list[:10]]

        return ProspectRecord(
            company_name=raw_record.get("name", ""),
            dba_name=None,
            industry_id=n_numbers[0] if n_numbers else None,
            phone=None,  # FAA data doesn't include phone
            email=None,
            website=None,
            address=address,
            city=raw_record.get("city", ""),
            state=raw_record.get("state", ""),
            zip_code=raw_record.get("zip_code", "")[:5] if raw_record.get("zip_code") else "",
            mailing_address=None,
            mailing_city=None,
            mailing_state=None,
            mailing_zip=None,
            business_size_metric=aircraft_count,
            business_size_label="Aircraft",
            employee_count=None,
            years_in_business=years_in_business,
            industry_data={
                "N-Numbers": ", ".join(n_numbers),
                "Aircraft Count": aircraft_count,
                "Owner Type": owner_type,
                "Aircraft Types": ", ".join(sorted(aircraft_types_in_fleet)),
                "Engine Types": ", ".join(sorted(engine_types_in_fleet)),
                "Newest Aircraft Year": newest_year if newest_year > 0 else "",
                "FAA Region": raw_record.get("region", ""),
            },
        )

    def get_scoring_rules(self) -> List[Dict[str, Any]]:
        """Return aviation-specific scoring rules."""
        return [
            # Fleet size scoring (multi-aircraft operators)
            {
                "name": "fleet_5_plus",
                "field": "business_size_metric",
                "rule_type": "range",
                "params": {"min": 5, "max": 100},
                "points": 30,
                "description": "Fleet operator (5+ aircraft)",
            },
            {
                "name": "fleet_2_4",
                "field": "business_size_metric",
                "rule_type": "range",
                "params": {"min": 2, "max": 4},
                "points": 20,
                "description": "Small fleet (2-4 aircraft)",
            },
            {
                "name": "single_aircraft",
                "field": "business_size_metric",
                "rule_type": "range",
                "params": {"min": 1, "max": 1},
                "points": 10,
                "description": "Single aircraft owner",
            },
            # Business entity types (better financing prospects)
            {
                "name": "corporation",
                "field": "industry_data",
                "rule_type": "custom",
                "points": 20,
                "description": "Corporation (established business)",
                "params": {"check_field": "Owner Type", "check_value": "Corporation"},
            },
            {
                "name": "llc",
                "field": "industry_data",
                "rule_type": "custom",
                "points": 15,
                "description": "LLC (business entity)",
                "params": {"check_field": "Owner Type", "check_value": "LLC"},
            },
            # High-value aircraft types
            {
                "name": "turbine_aircraft",
                "field": "industry_data",
                "rule_type": "custom",
                "points": 25,
                "description": "Turbine aircraft (high value)",
                "params": {"check_field": "Engine Types", "check_contains": "Turbo"},
            },
            {
                "name": "rotorcraft",
                "field": "industry_data",
                "rule_type": "custom",
                "points": 20,
                "description": "Rotorcraft/helicopter operator",
                "params": {"check_field": "Aircraft Types", "check_contains": "Rotorcraft"},
            },
            {
                "name": "multi_engine",
                "field": "industry_data",
                "rule_type": "custom",
                "points": 15,
                "description": "Multi-engine aircraft",
                "params": {"check_field": "Aircraft Types", "check_contains": "Multi-Engine"},
            },
            # Recent aircraft (indicates active buyer)
            {
                "name": "recent_aircraft",
                "field": "industry_data",
                "rule_type": "custom",
                "points": 15,
                "description": "Recent aircraft (2018+)",
                "params": {"check_field": "Newest Aircraft Year", "check_min": 2018},
            },
            # Established operator
            {
                "name": "established_5_plus",
                "field": "years_in_business",
                "rule_type": "range",
                "params": {"min": 5, "max": 100},
                "points": 10,
                "description": "Established 5+ years",
            },
        ]


# Utility functions for direct lookups

def lookup_by_n_number(n_number: str) -> Optional[Dict[str, Any]]:
    """
    Look up a specific aircraft by N-number.

    Args:
        n_number: Aircraft N-number (with or without N prefix)

    Returns:
        Aircraft data dictionary or None if not found
    """
    # Clean N-number
    n_number = n_number.upper().strip()
    if n_number.startswith("N"):
        n_number = n_number[1:]

    url = f"{FAA_REGISTRY_BASE}/aircraftinquiry/Search/NNumberResult"
    params = {"NNumbertxt": n_number}

    try:
        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()

        # Would need HTML parsing for full details
        # This is a simplified check
        if "N-Number" in response.text and "not found" not in response.text.lower():
            return {
                "n_number": f"N{n_number}",
                "found": True,
                "details_url": f"{url}?NNumbertxt={n_number}",
            }
        return None

    except Exception as e:
        print(f"Error looking up N{n_number}: {e}")
        return None


def search_by_name(
    owner_name: str,
    state: Optional[str] = None,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    """
    Search for aircraft by owner name.

    Note: This requires downloading the full FAA database for accurate results.
    Web inquiry has limited search capabilities.

    Args:
        owner_name: Owner name to search for
        state: Optional state filter
        limit: Maximum results

    Returns:
        List of matching records
    """
    # For name search, we'd need the full database
    # Return empty for now - full implementation would use cached data
    print("Note: Name search requires FAA database download. Use the prospector.run() method for bulk searches.")
    return []


def get_aircraft_by_state(
    state: str,
    aircraft_type: Optional[str] = None,
    owner_type: Optional[str] = None,
    limit: int = 100,
) -> List[Dict[str, Any]]:
    """
    Get aircraft registered in a specific state.

    Note: This requires downloading the full FAA database.

    Args:
        state: State abbreviation
        aircraft_type: Optional aircraft type filter
        owner_type: Optional owner type filter
        limit: Maximum results

    Returns:
        List of aircraft records
    """
    # Would require full database access
    # Consider implementing with cached data
    print("Note: State search requires FAA database download. Use the prospector.run() method for bulk searches.")
    return []
