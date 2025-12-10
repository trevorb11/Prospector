"""
Healthcare Industry Prospector (NPI Registry)
==============================================

This module provides prospect finding for the healthcare industry using
the CMS NPPES (National Plan and Provider Enumeration System) NPI Registry.

Data Source: CMS NPI Registry API
API: https://npiregistry.cms.hhs.gov/api/
Documentation: https://npiregistry.cms.hhs.gov/api-page

Free API, no authentication required.
Rate limit: Approximately 20,000 requests per day.
"""

import requests
import time
import re
from typing import Any, Dict, List, Optional
from datetime import datetime

from ..core.base import IndustryProspector, ProspectRecord
from ..core.scoring import ScoringRule, RuleType


# NPI Registry API endpoint
NPI_REGISTRY_URL = "https://npiregistry.cms.hhs.gov/api/"

# Healthcare taxonomy codes for high-value specialties (equipment financing potential)
HIGH_VALUE_TAXONOMIES = {
    # Dental
    "122300000X": "Dentist",
    "1223G0001X": "General Practice Dentist",
    "1223D0001X": "Dental Public Health",
    "1223E0200X": "Endodontist",
    "1223P0221X": "Pediatric Dentist",
    "1223S0112X": "Oral Surgeon",
    # Medical practices with equipment needs
    "207R00000X": "Internal Medicine",
    "207RC0000X": "Cardiovascular Disease",
    "2085R0202X": "Diagnostic Radiology",
    "261QR0200X": "Radiology Clinic",
    "207ND0900X": "Dermatology",
    "207W00000X": "Ophthalmology",
    "152W00000X": "Optometrist",
    "207L00000X": "Anesthesiology",
    "207Q00000X": "Family Medicine",
    "208000000X": "Pediatrics",
    "207V00000X": "Obstetrics & Gynecology",
    "208600000X": "Surgery",
    "2086S0120X": "Plastic Surgery",
    "2086S0122X": "Plastic Surgery (Reconstructive)",
    # Therapy/Rehab with equipment
    "225100000X": "Physical Therapist",
    "225X00000X": "Occupational Therapist",
    "231H00000X": "Audiologist",
    # Clinics and facilities
    "261QM1300X": "Multi-Specialty Clinic",
    "261QP2300X": "Primary Care Clinic",
    "261QU0200X": "Urgent Care Clinic",
    "282N00000X": "General Acute Care Hospital",
    "261QD0000X": "Ambulatory Surgery Center",
    "283Q00000X": "Psychiatric Hospital",
    # Labs and diagnostic
    "291U00000X": "Clinical Lab",
    "293D00000X": "Physiological Lab",
    # Pharmacy
    "333600000X": "Pharmacy",
    "3336C0002X": "Compounding Pharmacy",
}

# Organization entity types (Type 2 NPIs) - better financing prospects
ORGANIZATION_ENTITY_TYPES = ["2"]


class HealthcareProspector(IndustryProspector):
    """
    Prospector for the healthcare industry using CMS NPI Registry.

    Pulls healthcare provider data from the National Plan and Provider
    Enumeration System and filters based on location, specialty, and
    organization type.

    Configuration options:
        target_states: List of state abbreviations to search
        taxonomy_codes: List of taxonomy codes to search (specialty types)
        entity_types: List of entity types (1=Individual, 2=Organization)
        organization_only: If True, only search organizations (Type 2)
        limit_per_state: Maximum records to fetch per state
    """

    DEFAULT_CONFIG = {
        "target_states": ["FL", "GA", "TX", "CA", "IL", "NC", "TN", "OH", "PA", "NJ", "NY"],
        "taxonomy_codes": list(HIGH_VALUE_TAXONOMIES.keys()),
        "entity_types": ["2"],  # Organizations only by default
        "organization_only": True,
        "limit_per_state": 1000,
        "specialties": None,  # If set, filter by specialty names
    }

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize the healthcare prospector.

        Args:
            config: Configuration dictionary. Missing keys will use defaults.
        """
        merged_config = {**self.DEFAULT_CONFIG, **(config or {})}
        super().__init__(merged_config)
        self.api_url = NPI_REGISTRY_URL

    def get_industry_name(self) -> str:
        return "Healthcare (NPI Registry)"

    def _fetch_by_taxonomy(
        self,
        state: str,
        taxonomy_code: str,
        skip: int = 0,
        max_retries: int = 3
    ) -> List[Dict[str, Any]]:
        """Fetch data for a single state and taxonomy code."""
        params = {
            "version": "2.1",
            "state": state,
            "taxonomy_description": taxonomy_code,
            "limit": 200,  # Max allowed per request
            "skip": skip,
        }

        # Filter by entity type
        if self.config.get("organization_only") or self.config.get("entity_types"):
            entity_types = self.config.get("entity_types", ["2"])
            if "2" in entity_types:
                params["enumeration_type"] = "NPI-2"  # Organizations

        for attempt in range(max_retries):
            try:
                response = requests.get(
                    self.api_url,
                    params=params,
                    timeout=60
                )
                response.raise_for_status()
                data = response.json()

                if "results" in data:
                    return data["results"]
                return []

            except requests.exceptions.RequestException as e:
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)  # Exponential backoff
                else:
                    print(f" ERROR: {e}")
                    return []

        return []

    def _fetch_state_data(self, state: str) -> List[Dict[str, Any]]:
        """Fetch all healthcare providers for a state."""
        all_records = []
        seen_npis = set()

        print(f"  Fetching {state}...", end="", flush=True)

        # High-value specialty searches (these return good results)
        specialty_searches = [
            "*dental*",
            "*surgery*",
            "*radiology*",
            "*physical therap*",
            "*clinic*",
            "*ophthalmol*",
            "*orthop*",
            "*cardio*",
            "*dermatol*",
            "*chiropr*",
            "*urgent care*",
            "*family practice*",
            "*internal medicine*",
        ]

        for specialty in specialty_searches:
            if len(all_records) >= self.config["limit_per_state"]:
                break

            params = {
                "version": "2.1",
                "state": state,
                "taxonomy_description": specialty,
                "limit": 200,
            }

            if self.config.get("organization_only"):
                params["enumeration_type"] = "NPI-2"

            skip = 0
            max_per_specialty = min(200, self.config["limit_per_state"] // len(specialty_searches))

            while len(all_records) < self.config["limit_per_state"]:
                params["skip"] = skip

                try:
                    response = requests.get(self.api_url, params=params, timeout=60)
                    response.raise_for_status()
                    data = response.json()

                    results = data.get("results", [])
                    if not results:
                        break

                    # Deduplicate by NPI
                    for record in results:
                        npi = record.get("number")
                        if npi and npi not in seen_npis:
                            seen_npis.add(npi)
                            all_records.append(record)

                    if len(results) < 200 or skip >= max_per_specialty:
                        break

                    skip += 200
                    time.sleep(0.2)  # Rate limiting

                except requests.exceptions.RequestException as e:
                    break

            time.sleep(0.1)  # Between specialty searches

        print(f" {len(all_records)} records")
        return all_records[:self.config["limit_per_state"]]

    def fetch_prospects(self) -> List[Dict[str, Any]]:
        """Fetch prospect data from NPI Registry for all target states."""
        all_records = []

        print(f"\nFetching healthcare prospects from NPI Registry...")
        print(f"  States: {', '.join(self.config['target_states'])}")
        print(f"  Entity Type: {'Organizations' if self.config.get('organization_only') else 'All'}")
        print()

        for state in self.config["target_states"]:
            state_records = self._fetch_state_data(state)
            all_records.extend(state_records)
            time.sleep(0.5)  # Be nice to the API between states

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

    def parse_record(self, raw_record: Dict[str, Any]) -> ProspectRecord:
        """Convert raw NPI record to ProspectRecord."""
        # Get basic info
        basic = raw_record.get("basic", {})

        # Determine company name based on entity type
        enumeration_type = raw_record.get("enumeration_type", "")
        if enumeration_type == "NPI-2":
            # Organization
            company_name = basic.get("organization_name", "")
            dba_name = basic.get("doing_business_as")
        else:
            # Individual provider
            first_name = basic.get("first_name", "")
            last_name = basic.get("last_name", "")
            company_name = f"{first_name} {last_name}".strip()
            dba_name = basic.get("name_prefix")

        # Get address (primary practice location)
        addresses = raw_record.get("addresses", [])
        practice_address = None
        mailing_address = None

        for addr in addresses:
            if addr.get("address_purpose") == "LOCATION":
                practice_address = addr
            elif addr.get("address_purpose") == "MAILING":
                mailing_address = addr

        # Use practice address if available, otherwise mailing
        primary_addr = practice_address or mailing_address or {}
        mail_addr = mailing_address or {}

        # Get primary taxonomy (specialty)
        taxonomies = raw_record.get("taxonomies", [])
        primary_taxonomy = None
        all_specialties = []

        for tax in taxonomies:
            all_specialties.append(tax.get("desc", ""))
            if tax.get("primary"):
                primary_taxonomy = tax

        if not primary_taxonomy and taxonomies:
            primary_taxonomy = taxonomies[0]

        specialty = primary_taxonomy.get("desc", "") if primary_taxonomy else ""
        taxonomy_code = primary_taxonomy.get("code", "") if primary_taxonomy else ""

        # Get identifiers
        identifiers = raw_record.get("identifiers", [])
        other_ids = {id.get("identifier"): id.get("desc") for id in identifiers}

        # Calculate years since enumeration
        enumeration_date = basic.get("enumeration_date", "")
        years_active = None
        if enumeration_date:
            try:
                enum_year = int(enumeration_date.split("-")[0])
                years_active = datetime.now().year - enum_year
            except (ValueError, IndexError):
                pass

        return ProspectRecord(
            company_name=company_name,
            dba_name=dba_name,
            industry_id=str(raw_record.get("number", "")),
            phone=self.clean_phone_number(primary_addr.get("telephone_number")),
            email=None,  # NPI doesn't include email
            address=primary_addr.get("address_1", ""),
            city=primary_addr.get("city", ""),
            state=primary_addr.get("state", ""),
            zip_code=primary_addr.get("postal_code", "")[:5] if primary_addr.get("postal_code") else "",
            mailing_address=mail_addr.get("address_1"),
            mailing_city=mail_addr.get("city"),
            mailing_state=mail_addr.get("state"),
            mailing_zip=mail_addr.get("postal_code", "")[:5] if mail_addr.get("postal_code") else "",
            business_size_metric=None,  # NPI doesn't provide size metrics
            business_size_label="Providers",
            employee_count=None,
            years_in_business=years_active,
            industry_data={
                "NPI Number": raw_record.get("number"),
                "Entity Type": "Organization" if enumeration_type == "NPI-2" else "Individual",
                "Primary Specialty": specialty,
                "Taxonomy Code": taxonomy_code,
                "All Specialties": "; ".join(all_specialties) if all_specialties else "",
                "Enumeration Date": enumeration_date,
                "Last Updated": basic.get("last_updated", ""),
                "Status": basic.get("status", "A"),
            },
        )

    def get_scoring_rules(self) -> List[Dict[str, Any]]:
        """Return healthcare-specific scoring rules."""
        return [
            # High-value specialties (equipment-intensive)
            {
                "name": "dental_practice",
                "field": "industry_data",
                "rule_type": "custom",
                "points": 30,
                "description": "Dental practice (high equipment needs)",
                "params": {"check_field": "Primary Specialty", "check_contains": "Dent"},
            },
            {
                "name": "radiology_practice",
                "field": "industry_data",
                "rule_type": "custom",
                "points": 30,
                "description": "Radiology practice (expensive equipment)",
                "params": {"check_field": "Primary Specialty", "check_contains": "Radiol"},
            },
            {
                "name": "surgery_center",
                "field": "industry_data",
                "rule_type": "custom",
                "points": 25,
                "description": "Surgery center (high equipment costs)",
                "params": {"check_field": "Primary Specialty", "check_contains": "Surg"},
            },
            {
                "name": "ophthalmology",
                "field": "industry_data",
                "rule_type": "custom",
                "points": 25,
                "description": "Eye care (specialized equipment)",
                "params": {"check_field": "Primary Specialty", "check_contains": "Ophthal"},
            },
            {
                "name": "physical_therapy",
                "field": "industry_data",
                "rule_type": "custom",
                "points": 20,
                "description": "Physical therapy (equipment financing)",
                "params": {"check_field": "Primary Specialty", "check_contains": "Physical Therap"},
            },
            {
                "name": "clinic_facility",
                "field": "industry_data",
                "rule_type": "custom",
                "points": 20,
                "description": "Clinic or facility (larger operation)",
                "params": {"check_field": "Primary Specialty", "check_contains": "Clinic"},
            },
            # Organization vs Individual
            {
                "name": "is_organization",
                "field": "industry_data",
                "rule_type": "custom",
                "points": 15,
                "description": "Organization (vs solo practitioner)",
                "params": {"check_field": "Entity Type", "check_value": "Organization"},
            },
            # Established practice
            {
                "name": "established_5_plus",
                "field": "years_in_business",
                "rule_type": "range",
                "params": {"min": 5, "max": 100},
                "points": 15,
                "description": "Established 5+ years",
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
        ]


# Utility functions for direct lookups

def lookup_by_npi(npi_number: str) -> Optional[Dict[str, Any]]:
    """
    Look up a specific provider by NPI number.

    Args:
        npi_number: NPI number to look up

    Returns:
        Provider data dictionary or None if not found
    """
    params = {
        "version": "2.1",
        "number": npi_number,
    }

    try:
        response = requests.get(NPI_REGISTRY_URL, params=params, timeout=30)
        response.raise_for_status()
        data = response.json()

        if data.get("results"):
            record = data["results"][0]
            basic = record.get("basic", {})
            addresses = record.get("addresses", [])
            taxonomies = record.get("taxonomies", [])

            # Get practice address
            practice_addr = next(
                (a for a in addresses if a.get("address_purpose") == "LOCATION"),
                addresses[0] if addresses else {}
            )

            # Get primary specialty
            primary_tax = next(
                (t for t in taxonomies if t.get("primary")),
                taxonomies[0] if taxonomies else {}
            )

            return {
                "npi_number": record.get("number"),
                "organization_name": basic.get("organization_name"),
                "provider_name": f"{basic.get('first_name', '')} {basic.get('last_name', '')}".strip(),
                "entity_type": "Organization" if record.get("enumeration_type") == "NPI-2" else "Individual",
                "specialty": primary_tax.get("desc", ""),
                "phone": practice_addr.get("telephone_number"),
                "address": practice_addr.get("address_1"),
                "city": practice_addr.get("city"),
                "state": practice_addr.get("state"),
                "zip": practice_addr.get("postal_code"),
                "enumeration_date": basic.get("enumeration_date"),
                "last_updated": basic.get("last_updated"),
            }
        return None
    except Exception as e:
        print(f"Error looking up NPI {npi_number}: {e}")
        return None


def search_by_name(
    name: str,
    state: Optional[str] = None,
    specialty: Optional[str] = None,
    organization_only: bool = True,
    limit: int = 100,
) -> List[Dict[str, Any]]:
    """
    Search for healthcare providers by name.

    Args:
        name: Organization or provider name to search for
        state: Optional state filter
        specialty: Optional specialty filter
        organization_only: If True, only search organizations
        limit: Maximum results to return

    Returns:
        List of matching provider records
    """
    params = {
        "version": "2.1",
        "limit": min(limit, 200),
    }

    if organization_only:
        params["organization_name"] = f"*{name}*"
        params["enumeration_type"] = "NPI-2"
    else:
        params["name"] = f"*{name}*"

    if state:
        params["state"] = state

    if specialty:
        params["taxonomy_description"] = f"*{specialty}*"

    try:
        response = requests.get(NPI_REGISTRY_URL, params=params, timeout=30)
        response.raise_for_status()
        data = response.json()

        results = []
        for record in data.get("results", [])[:limit]:
            basic = record.get("basic", {})
            addresses = record.get("addresses", [])
            taxonomies = record.get("taxonomies", [])

            practice_addr = next(
                (a for a in addresses if a.get("address_purpose") == "LOCATION"),
                addresses[0] if addresses else {}
            )

            primary_tax = next(
                (t for t in taxonomies if t.get("primary")),
                taxonomies[0] if taxonomies else {}
            )

            results.append({
                "npi_number": record.get("number"),
                "name": basic.get("organization_name") or f"{basic.get('first_name', '')} {basic.get('last_name', '')}".strip(),
                "entity_type": "Organization" if record.get("enumeration_type") == "NPI-2" else "Individual",
                "specialty": primary_tax.get("desc", ""),
                "phone": practice_addr.get("telephone_number"),
                "city": practice_addr.get("city"),
                "state": practice_addr.get("state"),
            })

        return results
    except Exception as e:
        print(f"Error searching for '{name}': {e}")
        return []


def get_providers_by_city(
    city: str,
    state: str,
    specialty: Optional[str] = None,
    organization_only: bool = True,
) -> List[Dict[str, Any]]:
    """
    Get healthcare providers in a specific city.

    Args:
        city: City name
        state: State abbreviation
        specialty: Optional specialty filter
        organization_only: If True, only return organizations

    Returns:
        List of provider records
    """
    params = {
        "version": "2.1",
        "city": city,
        "state": state,
        "limit": 200,
    }

    if organization_only:
        params["enumeration_type"] = "NPI-2"

    if specialty:
        params["taxonomy_description"] = f"*{specialty}*"

    try:
        response = requests.get(NPI_REGISTRY_URL, params=params, timeout=30)
        response.raise_for_status()
        data = response.json()

        results = []
        for record in data.get("results", []):
            basic = record.get("basic", {})
            addresses = record.get("addresses", [])
            taxonomies = record.get("taxonomies", [])

            practice_addr = next(
                (a for a in addresses if a.get("address_purpose") == "LOCATION"),
                addresses[0] if addresses else {}
            )

            primary_tax = next(
                (t for t in taxonomies if t.get("primary")),
                taxonomies[0] if taxonomies else {}
            )

            results.append({
                "npi_number": record.get("number"),
                "name": basic.get("organization_name") or f"{basic.get('first_name', '')} {basic.get('last_name', '')}".strip(),
                "entity_type": "Organization" if record.get("enumeration_type") == "NPI-2" else "Individual",
                "specialty": primary_tax.get("desc", ""),
                "phone": practice_addr.get("telephone_number"),
                "address": practice_addr.get("address_1"),
                "city": practice_addr.get("city"),
                "state": practice_addr.get("state"),
                "zip": practice_addr.get("postal_code"),
            })

        return results
    except Exception as e:
        print(f"Error fetching providers in {city}, {state}: {e}")
        return []
