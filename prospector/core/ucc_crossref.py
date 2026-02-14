"""
UCC Cross-Reference Engine
===========================

Cross-references prospect lists against UCC (Uniform Commercial Code) filing
data to identify businesses with prior financing history.

UCC filings are the single strongest signal for MCA prospecting because:
- A UCC filing means the business has used secured financing before
- Recent filings indicate active financing needs
- Multiple filings indicate a business comfortable with alternative financing
- The secured party field reveals which lenders they've worked with

This module supports cross-referencing against:
- Connecticut UCC (data.ct.gov)
- Oregon UCC (data.oregon.gov)
- Colorado UCC (data.colorado.gov)
- Additional state APIs as they become available
"""

import os
import re
import requests
import time
from typing import Any, Dict, List, Optional, Callable, Tuple
from datetime import datetime
from difflib import SequenceMatcher


# State UCC API endpoints (Socrata-based)
UCC_ENDPOINTS = {
    "CT": {
        "url": "https://data.ct.gov/resource/xfev-8smz.json",
        "debtor_name_field": "debtor_nm_bus",
        "debtor_city_field": "debtor_ad_city",
        "debtor_state_field": "debtor_ad_state",
        "secured_party_field": "sec_party_nm_bus",
        "filing_date_field": "dt_accept",
        "filing_type_field": "cd_flng_type",
        "filing_number_field": "id_ucc_flng_nbr",
        "lapse_date_field": "dt_lapse",
    },
    "OR": {
        "url": "https://data.oregon.gov/resource/se62-vm8c.json",
        "debtor_name_field": "org_name",
        "debtor_city_field": "city",
        "debtor_state_field": "state",
        "secured_party_field": "sp_name",
        "filing_date_field": "file_date",
        "filing_type_field": "filing_type",
        "filing_number_field": "file_number",
        "lapse_date_field": "lapse_date",
    },
    "CO": {
        "url": "https://data.colorado.gov/resource/be9p-672s.json",
        "debtor_name_field": "debtor_name",
        "debtor_city_field": "debtor_city",
        "debtor_state_field": "debtor_state",
        "secured_party_field": "secured_party_name",
        "filing_date_field": "filing_date",
        "filing_type_field": "filing_type",
        "filing_number_field": "filing_number",
        "lapse_date_field": "lapse_date",
    },
}

# Common MCA/alternative lender names in secured party fields
KNOWN_MCA_LENDERS = [
    "CAPYTAL", "YELLOWSTONE", "BIZFUND", "CFG MERCHANT",
    "LIBERTAS", "FOX CAPITAL", "RAPID FINANCE", "PEARL CAPITAL",
    "GREEN CAPITAL", "FUNDWORKS", "MERCHANT CASH", "ADVANCE",
    "CAPITAL ADVANCE", "BUSINESS FUNDING", "FUNDER", "FUNDING",
    "SWIFT CAPITAL", "ON DECK", "ONDECK", "KABBAGE", "BLUEVINE",
    "CREDIBLY", "FUNDBOX", "CAN CAPITAL", "PAYPAL WORKING CAPITAL",
    "SQUARE CAPITAL", "CLEARCO", "SHOPIFY CAPITAL",
]


class UCCCrossReferencer:
    """
    Cross-references prospect data against UCC filings to identify
    businesses with prior financing history.
    """

    def __init__(
        self,
        states: Optional[List[str]] = None,
        app_token: Optional[str] = None,
        match_threshold: float = 0.80,
    ):
        """
        Initialize the UCC cross-referencer.

        Args:
            states: List of state codes to search (default: all available)
            app_token: Socrata API token for higher rate limits
            match_threshold: Minimum name similarity for matching (0-1)
        """
        self.states = states or list(UCC_ENDPOINTS.keys())
        self.app_token = app_token or os.getenv("SOCRATA_APP_TOKEN")
        self.match_threshold = match_threshold
        self.session = requests.Session()
        if self.app_token:
            self.session.headers["X-App-Token"] = self.app_token
        self._cache: Dict[str, List[Dict]] = {}

    @staticmethod
    def clean_name(name: str) -> str:
        """Normalize a company name for matching."""
        if not name:
            return ""
        name = name.upper().strip()
        suffixes = [
            " LLC", " INC", " CORP", " CO", " LTD", " LP", " LLP",
            " INCORPORATED", " CORPORATION", " COMPANY", " LIMITED",
            " ENTERPRISES", " HOLDINGS", " GROUP", " PARTNERS",
            " TRUCKING", " TRANSPORT", " LOGISTICS", " SERVICES",
        ]
        for suffix in suffixes:
            name = name.replace(suffix, "")
        name = re.sub(r"[^\w\s]", "", name)
        name = " ".join(name.split())
        return name

    @staticmethod
    def name_similarity(name1: str, name2: str) -> float:
        """Calculate similarity between two company names."""
        clean1 = UCCCrossReferencer.clean_name(name1)
        clean2 = UCCCrossReferencer.clean_name(name2)
        if not clean1 or not clean2:
            return 0.0
        return SequenceMatcher(None, clean1, clean2).ratio()

    def search_ucc_by_name(
        self,
        company_name: str,
        state: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """
        Search for UCC filings by debtor name across configured states.

        Args:
            company_name: Business name to search for
            state: Specific state to search (or None for all)
            limit: Max results per state

        Returns:
            List of matching UCC filing records
        """
        results = []
        search_states = [state] if state and state in UCC_ENDPOINTS else self.states

        for st in search_states:
            if st not in UCC_ENDPOINTS:
                continue

            endpoint = UCC_ENDPOINTS[st]
            clean_name = company_name.upper().strip().replace("'", "''")

            params = {
                "$where": f"upper({endpoint['debtor_name_field']}) like '%{clean_name}%'",
                "$limit": str(limit),
                "$order": f"{endpoint['filing_date_field']} DESC",
            }

            try:
                response = self.session.get(
                    endpoint["url"], params=params, timeout=30
                )
                response.raise_for_status()
                records = response.json()

                for record in records:
                    results.append({
                        "state": st,
                        "debtor_name": record.get(endpoint["debtor_name_field"], ""),
                        "debtor_city": record.get(endpoint["debtor_city_field"], ""),
                        "secured_party": record.get(endpoint["secured_party_field"], ""),
                        "filing_date": record.get(endpoint["filing_date_field"], ""),
                        "filing_type": record.get(endpoint["filing_type_field"], ""),
                        "filing_number": record.get(endpoint["filing_number_field"], ""),
                        "lapse_date": record.get(endpoint["lapse_date_field"], ""),
                        "source_state": st,
                    })

                time.sleep(0.3)  # Rate limiting

            except requests.RequestException:
                continue

        return results

    def cross_reference_prospects(
        self,
        prospects: List[Any],
        progress_callback: Optional[Callable[[int, str], None]] = None,
    ) -> Dict[str, List[Dict]]:
        """
        Cross-reference a list of prospect records against UCC filings.

        Args:
            prospects: List of ProspectRecord objects
            progress_callback: Optional progress callback (percent, message)

        Returns:
            Dictionary mapping company names (uppercase) to their UCC filings
        """
        matches: Dict[str, List[Dict]] = {}
        total = len(prospects)

        if progress_callback:
            progress_callback(0, f"Cross-referencing {total} prospects against UCC filings...")

        # Build a set of unique company names to search
        unique_companies: Dict[str, Any] = {}
        for prospect in prospects:
            name = (prospect.company_name or "").upper().strip()
            if name and name not in unique_companies:
                unique_companies[name] = prospect

        unique_count = len(unique_companies)
        if progress_callback:
            progress_callback(5, f"Searching UCC records for {unique_count} unique companies...")

        for i, (name, prospect) in enumerate(unique_companies.items()):
            if progress_callback and i % 10 == 0:
                pct = 5 + int(85 * i / unique_count)
                progress_callback(pct, f"Checking UCC filings: {i}/{unique_count}...")

            # Search UCC by company name
            # Use the first significant word(s) for broader matching
            search_name = self.clean_name(name)
            words = search_name.split()
            if len(words) > 3:
                search_term = " ".join(words[:3])
            else:
                search_term = search_name

            if not search_term or len(search_term) < 3:
                continue

            filings = self.search_ucc_by_name(
                search_term,
                state=prospect.state if hasattr(prospect, "state") else None,
                limit=20,
            )

            # Filter by name similarity
            matched_filings = []
            for filing in filings:
                debtor = filing.get("debtor_name", "")
                similarity = self.name_similarity(name, debtor)
                if similarity >= self.match_threshold:
                    filing["match_score"] = round(similarity, 3)
                    filing["is_mca_lender"] = self._is_mca_lender(filing.get("secured_party", ""))
                    matched_filings.append(filing)

            if matched_filings:
                matches[name] = matched_filings

            time.sleep(0.2)  # Rate limiting

        if progress_callback:
            progress_callback(95, f"Found UCC matches for {len(matches)} companies...")

        self._cache.update(matches)

        if progress_callback:
            progress_callback(100, f"UCC cross-reference complete: {len(matches)} matches found")

        return matches

    def _is_mca_lender(self, secured_party: str) -> bool:
        """Check if the secured party is a known MCA/alternative lender."""
        if not secured_party:
            return False
        sp_upper = secured_party.upper()
        return any(lender in sp_upper for lender in KNOWN_MCA_LENDERS)

    def get_financing_summary(self, company_name: str) -> Dict[str, Any]:
        """
        Get a financing history summary for a company.

        Args:
            company_name: Company name to look up

        Returns:
            Summary dict with filing count, lenders, dates, etc.
        """
        name = company_name.upper().strip()
        filings = self._cache.get(name, [])

        if not filings:
            filings = self.search_ucc_by_name(company_name)

        if not filings:
            return {
                "has_financing_history": False,
                "filing_count": 0,
                "lenders": [],
                "most_recent_filing": None,
                "has_mca_history": False,
            }

        lenders = list(set(f.get("secured_party", "") for f in filings if f.get("secured_party")))
        mca_lenders = [l for l in lenders if self._is_mca_lender(l)]
        dates = [f.get("filing_date", "") for f in filings if f.get("filing_date")]
        most_recent = max(dates) if dates else None

        return {
            "has_financing_history": True,
            "filing_count": len(filings),
            "lenders": lenders,
            "mca_lenders": mca_lenders,
            "has_mca_history": len(mca_lenders) > 0,
            "most_recent_filing": most_recent[:10] if most_recent else None,
            "states_with_filings": list(set(f.get("source_state", "") for f in filings)),
        }

    def bulk_search(
        self,
        state: str,
        filed_after: Optional[str] = None,
        limit: int = 5000,
        progress_callback: Optional[Callable[[int, str], None]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Pull recent UCC filings in bulk for a state.
        Useful for building a local index to cross-reference against.

        Args:
            state: State code (CT, OR, CO)
            filed_after: Only get filings after this date (YYYY-MM-DD)
            limit: Maximum records
            progress_callback: Progress callback

        Returns:
            List of UCC filing records
        """
        if state not in UCC_ENDPOINTS:
            return []

        endpoint = UCC_ENDPOINTS[state]
        all_records = []
        offset = 0
        batch_size = 1000

        if progress_callback:
            progress_callback(0, f"Fetching recent UCC filings from {state}...")

        while len(all_records) < limit:
            params = {
                "$limit": str(min(batch_size, limit - len(all_records))),
                "$offset": str(offset),
                "$order": f"{endpoint['filing_date_field']} DESC",
            }

            if filed_after:
                params["$where"] = f"{endpoint['filing_date_field']} >= '{filed_after}T00:00:00.000'"

            try:
                response = self.session.get(
                    endpoint["url"], params=params, timeout=60
                )
                response.raise_for_status()
                records = response.json()

                if not records:
                    break

                for record in records:
                    all_records.append({
                        "state": state,
                        "debtor_name": record.get(endpoint["debtor_name_field"], ""),
                        "debtor_city": record.get(endpoint["debtor_city_field"], ""),
                        "secured_party": record.get(endpoint["secured_party_field"], ""),
                        "filing_date": record.get(endpoint["filing_date_field"], ""),
                        "filing_type": record.get(endpoint["filing_type_field"], ""),
                        "filing_number": record.get(endpoint["filing_number_field"], ""),
                    })

                offset += len(records)

                if progress_callback:
                    pct = min(90, int(90 * len(all_records) / limit))
                    progress_callback(pct, f"Fetched {len(all_records)} filings from {state}...")

                if len(records) < batch_size:
                    break

                time.sleep(0.3)

            except requests.RequestException:
                break

        if progress_callback:
            progress_callback(100, f"Loaded {len(all_records)} UCC filings from {state}")

        return all_records
