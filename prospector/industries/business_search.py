"""
Business Search & Enrichment APIs
===================================

Provides additional data enrichment through multiple business data APIs
that complement the existing government data sources:

1. OpenCorporates - Business registration data across all 50 states
2. Google Places - Verified business info, reviews, phone, hours
3. Yelp Fusion - Business ratings, reviews, claimed status
4. SEC EDGAR - Public company filings (for filtering out public companies)

These APIs add the critical missing signals:
- Is the business currently active and operating?
- Can we verify the phone number and address?
- What do customers say about the business (reviews = revenue proxy)?
- Is this a public company (filter out - they don't need MCA)?
"""

import os
import re
import requests
import time
from typing import Any, Dict, List, Optional, Callable
from datetime import datetime


# =============================================================================
# OpenCorporates - Business Registration Data
# =============================================================================

OPENCORPORATES_API = "https://api.opencorporates.com/v0.4"


class OpenCorporatesSearcher:
    """
    Search business registration data via OpenCorporates API.

    OpenCorporates aggregates business registry data from all 50 US states
    and 140+ countries. Free tier allows basic searches.

    Provides:
    - Business entity name, type, status
    - Registration date (for time-in-business)
    - Registered agent info
    - Jurisdiction
    - Officers/directors (paid tier)

    Rate limits: Free tier ~500 requests/month, paid plans available.
    API key: Optional (set OPENCORPORATES_API_KEY env var)
    """

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("OPENCORPORATES_API_KEY")
        self.base_url = OPENCORPORATES_API
        self.session = requests.Session()

    def search_company(
        self,
        company_name: str,
        jurisdiction: Optional[str] = None,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """
        Search for a company by name.

        Args:
            company_name: Company name to search
            jurisdiction: US state code (e.g., "us_fl" for Florida)
            limit: Max results

        Returns:
            List of matching company records
        """
        params = {
            "q": company_name,
            "per_page": min(limit, 30),
        }

        if jurisdiction:
            # OpenCorporates uses format "us_fl" for Florida, etc.
            if len(jurisdiction) == 2:
                jurisdiction = f"us_{jurisdiction.lower()}"
            params["jurisdiction_code"] = jurisdiction

        if self.api_key:
            params["api_token"] = self.api_key

        try:
            response = self.session.get(
                f"{self.base_url}/companies/search",
                params=params,
                timeout=30,
            )
            response.raise_for_status()
            data = response.json()

            results = []
            companies = data.get("results", {}).get("companies", [])

            for item in companies:
                company = item.get("company", {})
                results.append({
                    "name": company.get("name", ""),
                    "company_number": company.get("company_number", ""),
                    "jurisdiction": company.get("jurisdiction_code", ""),
                    "status": company.get("current_status", ""),
                    "incorporation_date": company.get("incorporation_date"),
                    "company_type": company.get("company_type", ""),
                    "registered_address": company.get("registered_address_in_full", ""),
                    "opencorporates_url": company.get("opencorporates_url", ""),
                    "agent_name": company.get("agent_name", ""),
                    "agent_address": company.get("agent_address", ""),
                    "source": "OpenCorporates",
                })

            return results

        except requests.RequestException as e:
            print(f"OpenCorporates search error: {e}")
            return []

    def get_company_details(self, jurisdiction: str, company_number: str) -> Optional[Dict[str, Any]]:
        """
        Get detailed company information.

        Args:
            jurisdiction: Jurisdiction code (e.g., "us_fl")
            company_number: Company registration number

        Returns:
            Detailed company record or None
        """
        params = {}
        if self.api_key:
            params["api_token"] = self.api_key

        try:
            response = self.session.get(
                f"{self.base_url}/companies/{jurisdiction}/{company_number}",
                params=params,
                timeout=30,
            )
            response.raise_for_status()
            data = response.json()

            company = data.get("results", {}).get("company", {})
            if not company:
                return None

            result = {
                "name": company.get("name", ""),
                "company_number": company.get("company_number", ""),
                "jurisdiction": company.get("jurisdiction_code", ""),
                "status": company.get("current_status", ""),
                "incorporation_date": company.get("incorporation_date"),
                "dissolution_date": company.get("dissolution_date"),
                "company_type": company.get("company_type", ""),
                "registered_address": company.get("registered_address_in_full", ""),
                "agent_name": company.get("agent_name", ""),
                "agent_address": company.get("agent_address", ""),
                "previous_names": [
                    pn.get("company_name", "") for pn in company.get("previous_names", [])
                ],
                "source": "OpenCorporates",
            }

            # Calculate years in business
            inc_date = company.get("incorporation_date")
            if inc_date:
                try:
                    inc_year = int(inc_date[:4])
                    result["years_in_business"] = datetime.now().year - inc_year
                except (ValueError, IndexError):
                    pass

            return result

        except requests.RequestException as e:
            print(f"OpenCorporates detail error: {e}")
            return None

    def enrich_prospect(self, prospect: Any) -> Dict[str, Any]:
        """
        Enrich a ProspectRecord with OpenCorporates data.

        Args:
            prospect: ProspectRecord to enrich

        Returns:
            Dictionary of enrichment data
        """
        enrichment = {"opencorporates_matched": False}

        company_name = prospect.company_name
        state = prospect.state

        if not company_name:
            return enrichment

        results = self.search_company(company_name, jurisdiction=state, limit=5)

        if results:
            # Take the best match
            best = results[0]
            enrichment.update({
                "opencorporates_matched": True,
                "oc_name": best.get("name", ""),
                "oc_status": best.get("status", ""),
                "oc_incorporation_date": best.get("incorporation_date"),
                "oc_company_type": best.get("company_type", ""),
                "oc_jurisdiction": best.get("jurisdiction", ""),
                "oc_registered_address": best.get("registered_address", ""),
            })

            # Update years_in_business if we have a better value
            inc_date = best.get("incorporation_date")
            if inc_date:
                try:
                    inc_year = int(inc_date[:4])
                    enrichment["oc_years_in_business"] = datetime.now().year - inc_year
                except (ValueError, IndexError):
                    pass

        return enrichment


# =============================================================================
# Google Places API - Verified Business Info
# =============================================================================

GOOGLE_PLACES_BASE = "https://maps.googleapis.com/maps/api/place"


class GooglePlacesSearcher:
    """
    Search and verify businesses using Google Places API.

    Provides:
    - Verified phone number
    - Business hours
    - Rating and review count (revenue proxy)
    - Business status (operational, closed, etc.)
    - Website URL
    - Photos (optional)

    Pricing: $0.017 per basic request, $0.032 per detail request
    API key: Required (set GOOGLE_PLACES_API_KEY env var)
    """

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("GOOGLE_PLACES_API_KEY")
        self.session = requests.Session()

    def is_configured(self) -> bool:
        """Check if the Google Places API key is configured."""
        return bool(self.api_key)

    def search_business(
        self,
        business_name: str,
        city: Optional[str] = None,
        state: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Search for a business on Google Places.

        Args:
            business_name: Business name
            city: City for location context
            state: State for location context

        Returns:
            Best matching place result or None
        """
        if not self.api_key:
            return None

        query = business_name
        if city and state:
            query += f" {city} {state}"
        elif state:
            query += f" {state}"

        params = {
            "input": query,
            "inputtype": "textquery",
            "fields": "place_id,name,formatted_address,business_status,geometry",
            "key": self.api_key,
        }

        try:
            response = self.session.get(
                f"{GOOGLE_PLACES_BASE}/findplacefromtext/json",
                params=params,
                timeout=15,
            )
            response.raise_for_status()
            data = response.json()

            candidates = data.get("candidates", [])
            if candidates:
                return candidates[0]
            return None

        except requests.RequestException:
            return None

    def get_place_details(self, place_id: str) -> Optional[Dict[str, Any]]:
        """
        Get detailed information about a place.

        Args:
            place_id: Google Place ID

        Returns:
            Place details or None
        """
        if not self.api_key:
            return None

        params = {
            "place_id": place_id,
            "fields": (
                "name,formatted_phone_number,international_phone_number,"
                "website,url,rating,user_ratings_total,business_status,"
                "opening_hours,formatted_address,types,price_level"
            ),
            "key": self.api_key,
        }

        try:
            response = self.session.get(
                f"{GOOGLE_PLACES_BASE}/details/json",
                params=params,
                timeout=15,
            )
            response.raise_for_status()
            data = response.json()

            result = data.get("result", {})
            if not result:
                return None

            return {
                "name": result.get("name", ""),
                "phone": result.get("formatted_phone_number", ""),
                "international_phone": result.get("international_phone_number", ""),
                "website": result.get("website", ""),
                "google_maps_url": result.get("url", ""),
                "rating": result.get("rating"),
                "review_count": result.get("user_ratings_total"),
                "business_status": result.get("business_status", ""),
                "address": result.get("formatted_address", ""),
                "is_open_now": result.get("opening_hours", {}).get("open_now"),
                "price_level": result.get("price_level"),
                "types": result.get("types", []),
                "source": "Google Places",
            }

        except requests.RequestException:
            return None

    def enrich_prospect(self, prospect: Any) -> Dict[str, Any]:
        """
        Enrich a ProspectRecord with Google Places data.

        Args:
            prospect: ProspectRecord to enrich

        Returns:
            Dictionary of enrichment data
        """
        enrichment = {"google_places_matched": False}

        if not self.api_key:
            return enrichment

        # Search for the business
        result = self.search_business(
            prospect.company_name,
            city=prospect.city,
            state=prospect.state,
        )

        if not result:
            return enrichment

        place_id = result.get("place_id")
        if not place_id:
            return enrichment

        # Get details
        details = self.get_place_details(place_id)
        if not details:
            return enrichment

        enrichment.update({
            "google_places_matched": True,
            "gp_phone": details.get("phone", ""),
            "gp_website": details.get("website", ""),
            "gp_rating": details.get("rating"),
            "gp_review_count": details.get("review_count"),
            "gp_business_status": details.get("business_status", ""),
            "gp_address": details.get("address", ""),
            "gp_google_maps_url": details.get("google_maps_url", ""),
        })

        return enrichment


# =============================================================================
# Yelp Fusion API - Business Reviews & Status
# =============================================================================

YELP_API_BASE = "https://api.yelp.com/v3"


class YelpSearcher:
    """
    Search and verify businesses using Yelp Fusion API.

    Provides:
    - Rating and review count
    - Business claimed status (owner has claimed = active engagement)
    - Phone number
    - Price range
    - Categories/industry
    - Transaction types (delivery, pickup, etc.)

    Rate limits: 5,000 API calls/day on free tier
    API key: Required (set YELP_API_KEY env var)
    """

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("YELP_API_KEY")
        self.session = requests.Session()
        if self.api_key:
            self.session.headers["Authorization"] = f"Bearer {self.api_key}"

    def is_configured(self) -> bool:
        """Check if the Yelp API key is configured."""
        return bool(self.api_key)

    def search_business(
        self,
        business_name: str,
        city: Optional[str] = None,
        state: Optional[str] = None,
        limit: int = 5,
    ) -> List[Dict[str, Any]]:
        """
        Search for a business on Yelp.

        Args:
            business_name: Business name
            city: City for location
            state: State for location
            limit: Max results

        Returns:
            List of matching business results
        """
        if not self.api_key:
            return []

        params = {
            "term": business_name,
            "limit": limit,
        }

        location_parts = []
        if city:
            location_parts.append(city)
        if state:
            location_parts.append(state)
        if location_parts:
            params["location"] = ", ".join(location_parts)
        else:
            return []  # Yelp requires location

        try:
            response = self.session.get(
                f"{YELP_API_BASE}/businesses/search",
                params=params,
                timeout=15,
            )
            response.raise_for_status()
            data = response.json()

            results = []
            for biz in data.get("businesses", []):
                results.append({
                    "id": biz.get("id"),
                    "name": biz.get("name", ""),
                    "phone": biz.get("display_phone", ""),
                    "rating": biz.get("rating"),
                    "review_count": biz.get("review_count"),
                    "price": biz.get("price", ""),
                    "is_claimed": biz.get("is_claimed"),
                    "is_closed": biz.get("is_closed", False),
                    "categories": [c.get("title", "") for c in biz.get("categories", [])],
                    "address": ", ".join(biz.get("location", {}).get("display_address", [])),
                    "transactions": biz.get("transactions", []),
                    "url": biz.get("url", ""),
                    "source": "Yelp",
                })

            return results

        except requests.RequestException:
            return []

    def enrich_prospect(self, prospect: Any) -> Dict[str, Any]:
        """
        Enrich a ProspectRecord with Yelp data.

        Args:
            prospect: ProspectRecord to enrich

        Returns:
            Dictionary of enrichment data
        """
        enrichment = {"yelp_matched": False}

        if not self.api_key:
            return enrichment

        results = self.search_business(
            prospect.company_name,
            city=prospect.city,
            state=prospect.state,
            limit=3,
        )

        if results:
            best = results[0]
            enrichment.update({
                "yelp_matched": True,
                "yelp_phone": best.get("phone", ""),
                "yelp_rating": best.get("rating"),
                "yelp_review_count": best.get("review_count"),
                "yelp_price": best.get("price", ""),
                "yelp_is_claimed": best.get("is_claimed"),
                "yelp_is_closed": best.get("is_closed", False),
                "yelp_categories": "; ".join(best.get("categories", [])),
                "yelp_url": best.get("url", ""),
            })

        return enrichment


# =============================================================================
# SEC EDGAR - Public Company Filter
# =============================================================================

SEC_EDGAR_BASE = "https://efts.sec.gov/LATEST/search-index"
SEC_EDGAR_COMPANY = "https://efts.sec.gov/LATEST/search-index"
SEC_FULL_TEXT = "https://efts.sec.gov/LATEST/search-index"


class SECEdgarSearcher:
    """
    Search SEC EDGAR to identify public companies.

    Public companies typically don't need MCA - they have access to
    capital markets, bank credit facilities, and institutional lending.
    Identifying and filtering them out improves lead quality.

    API: Free, no authentication required.
    Rate limit: 10 requests/second with User-Agent header required.
    """

    COMPANY_SEARCH_URL = "https://efts.sec.gov/LATEST/search-index"

    def __init__(self, user_agent: str = "Prospector/1.0 (MCA Lead Tool)"):
        self.session = requests.Session()
        self.session.headers["User-Agent"] = user_agent

    def is_public_company(self, company_name: str) -> bool:
        """
        Check if a company is publicly traded (has SEC filings).

        Args:
            company_name: Company name to check

        Returns:
            True if the company appears to be publicly traded
        """
        try:
            params = {
                "q": f'"{company_name}"',
                "dateRange": "custom",
                "startdt": "2020-01-01",
                "enddt": datetime.now().strftime("%Y-%m-%d"),
                "forms": "10-K,10-Q",  # Annual/quarterly reports = definitely public
            }

            response = self.session.get(
                "https://efts.sec.gov/LATEST/search-index",
                params=params,
                timeout=15,
            )

            if response.status_code == 200:
                data = response.json()
                total = data.get("hits", {}).get("total", {}).get("value", 0)
                return total > 0

        except (requests.RequestException, ValueError):
            pass

        return False

    def search_company(self, company_name: str) -> List[Dict[str, Any]]:
        """
        Search for a company in SEC EDGAR.

        Args:
            company_name: Company name

        Returns:
            List of matching SEC entity records
        """
        try:
            # Use the EDGAR full-text search API
            response = self.session.get(
                "https://efts.sec.gov/LATEST/search-index",
                params={
                    "q": company_name,
                    "forms": "10-K",
                },
                timeout=15,
            )

            if response.status_code == 200:
                data = response.json()
                hits = data.get("hits", {}).get("hits", [])

                results = []
                for hit in hits[:5]:
                    source = hit.get("_source", {})
                    results.append({
                        "entity_name": source.get("entity_name", ""),
                        "file_num": source.get("file_num", ""),
                        "file_date": source.get("file_date", ""),
                        "form_type": source.get("form_type", ""),
                    })

                return results

        except (requests.RequestException, ValueError):
            pass

        return []


# =============================================================================
# Secretary of State Business Filings - New Business Registrations
# =============================================================================

# State SOS data portals (Socrata-based where available)
SOS_ENDPOINTS = {
    "FL": {
        "url": "https://data.florida.gov/resource/y4wt-dxfq.json",
        "name_field": "corp_name",
        "status_field": "status",
        "filed_date_field": "file_date",
        "state_field": "state",
        "type_field": "type",
    },
    "CO": {
        "url": "https://data.colorado.gov/resource/4ykn-tg5h.json",
        "name_field": "entity_name",
        "status_field": "entity_status",
        "filed_date_field": "entity_formed_date",
        "state_field": "principal_state",
        "type_field": "entity_type",
    },
    "CT": {
        "url": "https://data.ct.gov/resource/xfev-8smz.json",
        "name_field": "business_name",
        "status_field": "status",
        "filed_date_field": "date_filed",
        "state_field": "state",
        "type_field": "business_type",
    },
}


class SecretaryOfStateSearcher:
    """
    Search state Secretary of State business registration data.

    New business registrations are a key trigger signal:
    - Recently registered = needs working capital
    - LLC/Corp registration = formalized business, MCA-eligible
    - Active status = verified operating business

    Available for states with open data portals (FL, CO, CT, and more).
    """

    def __init__(self, app_token: Optional[str] = None):
        self.app_token = app_token or os.getenv("SOCRATA_APP_TOKEN")
        self.session = requests.Session()
        if self.app_token:
            self.session.headers["X-App-Token"] = self.app_token

    def search_new_businesses(
        self,
        state: str,
        filed_after: Optional[str] = None,
        business_types: Optional[List[str]] = None,
        limit: int = 1000,
        progress_callback: Optional[Callable[[int, str], None]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Search for recently registered businesses.

        Args:
            state: State code (FL, CO, CT)
            filed_after: Only get businesses filed after this date (YYYY-MM-DD)
            business_types: Filter by business type (LLC, CORP, etc.)
            limit: Maximum records
            progress_callback: Progress callback

        Returns:
            List of business registration records
        """
        if state not in SOS_ENDPOINTS:
            if progress_callback:
                progress_callback(100, f"No SOS data available for {state}")
            return []

        endpoint = SOS_ENDPOINTS[state]

        if progress_callback:
            progress_callback(5, f"Searching {state} Secretary of State records...")

        where_clauses = []

        if filed_after:
            where_clauses.append(f"{endpoint['filed_date_field']} >= '{filed_after}T00:00:00.000'")

        if business_types:
            type_conditions = " OR ".join([
                f"upper({endpoint['type_field']}) like '%{bt.upper()}%'"
                for bt in business_types
            ])
            where_clauses.append(f"({type_conditions})")

        # Only active businesses
        where_clauses.append(f"upper({endpoint['status_field']}) like '%ACTIVE%'")

        all_records = []
        offset = 0
        batch_size = 1000

        while len(all_records) < limit:
            params = {
                "$limit": str(min(batch_size, limit - len(all_records))),
                "$offset": str(offset),
                "$order": f"{endpoint['filed_date_field']} DESC",
            }

            if where_clauses:
                params["$where"] = " AND ".join(where_clauses)

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
                        "company_name": record.get(endpoint["name_field"], ""),
                        "status": record.get(endpoint["status_field"], ""),
                        "filed_date": record.get(endpoint["filed_date_field"], ""),
                        "business_type": record.get(endpoint["type_field"], ""),
                        "state": state,
                        "source": f"{state} Secretary of State",
                    })

                offset += len(records)

                if progress_callback:
                    pct = min(90, 5 + int(85 * len(all_records) / limit))
                    progress_callback(pct, f"Fetched {len(all_records)} {state} business registrations...")

                if len(records) < batch_size:
                    break

                time.sleep(0.3)

            except requests.RequestException as e:
                if progress_callback:
                    progress_callback(0, f"API error: {str(e)}")
                break

        if progress_callback:
            progress_callback(100, f"Found {len(all_records)} business registrations in {state}")

        return all_records

    def search_company(
        self,
        company_name: str,
        state: str,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """
        Search for a specific company in SOS records.

        Args:
            company_name: Company name to search
            state: State code
            limit: Max results

        Returns:
            List of matching business records
        """
        if state not in SOS_ENDPOINTS:
            return []

        endpoint = SOS_ENDPOINTS[state]
        clean_name = company_name.upper().strip().replace("'", "''")

        params = {
            "$where": f"upper({endpoint['name_field']}) like '%{clean_name}%'",
            "$limit": str(limit),
            "$order": f"{endpoint['filed_date_field']} DESC",
        }

        try:
            response = self.session.get(
                endpoint["url"], params=params, timeout=30
            )
            response.raise_for_status()
            records = response.json()

            return [
                {
                    "company_name": r.get(endpoint["name_field"], ""),
                    "status": r.get(endpoint["status_field"], ""),
                    "filed_date": r.get(endpoint["filed_date_field"], ""),
                    "business_type": r.get(endpoint["type_field"], ""),
                    "state": state,
                    "source": f"{state} Secretary of State",
                }
                for r in records
            ]

        except requests.RequestException:
            return []


# =============================================================================
# Composite Enrichment Pipeline
# =============================================================================


class BusinessEnrichmentPipeline:
    """
    Orchestrates enrichment across all available business data APIs.

    Runs enrichment in priority order:
    1. OpenCorporates (time-in-business, entity type, status)
    2. Google Places (verified phone, reviews, active status)
    3. Yelp (reviews, claimed status, price level)
    4. SEC EDGAR (public company filter)

    Only calls APIs that are configured (have API keys set).
    """

    def __init__(self):
        self.opencorporates = OpenCorporatesSearcher()
        self.google_places = GooglePlacesSearcher()
        self.yelp = YelpSearcher()
        self.sec_edgar = SECEdgarSearcher()

    def get_available_sources(self) -> List[str]:
        """Return list of configured/available data sources."""
        sources = ["OpenCorporates (free tier)", "SEC EDGAR (free)"]
        if self.google_places.is_configured():
            sources.append("Google Places")
        if self.yelp.is_configured():
            sources.append("Yelp Fusion")
        return sources

    def enrich_prospect(
        self,
        prospect: Any,
        sources: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Enrich a single prospect with all available business data.

        Args:
            prospect: ProspectRecord to enrich
            sources: Specific sources to use (None = all available)

        Returns:
            Combined enrichment data from all sources
        """
        enrichment = {}
        use_all = sources is None

        # OpenCorporates - always available (free)
        if use_all or "opencorporates" in (sources or []):
            oc_data = self.opencorporates.enrich_prospect(prospect)
            enrichment.update(oc_data)
            time.sleep(0.5)  # Rate limiting

        # Google Places - if API key is set
        if (use_all or "google_places" in (sources or [])) and self.google_places.is_configured():
            gp_data = self.google_places.enrich_prospect(prospect)
            enrichment.update(gp_data)
            time.sleep(0.2)

        # Yelp - if API key is set
        if (use_all or "yelp" in (sources or [])) and self.yelp.is_configured():
            yelp_data = self.yelp.enrich_prospect(prospect)
            enrichment.update(yelp_data)
            time.sleep(0.2)

        # SEC EDGAR - free, but only check for larger businesses
        if use_all or "sec_edgar" in (sources or []):
            is_public = self.sec_edgar.is_public_company(prospect.company_name)
            enrichment["is_public_company"] = is_public
            if is_public:
                enrichment["mca_note"] = "Public company - likely has access to bank credit facilities"
            time.sleep(0.1)

        return enrichment

    def enrich_batch(
        self,
        prospects: List[Any],
        sources: Optional[List[str]] = None,
        progress_callback: Optional[Callable[[int, str], None]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Enrich a batch of prospects.

        Args:
            prospects: List of ProspectRecord objects
            sources: Specific sources to use
            progress_callback: Progress callback

        Returns:
            List of enrichment dictionaries (same order as input)
        """
        results = []
        total = len(prospects)

        if progress_callback:
            progress_callback(0, f"Enriching {total} prospects with business data...")

        for i, prospect in enumerate(prospects):
            if progress_callback:
                pct = int(100 * i / total)
                progress_callback(pct, f"Enriching {i+1}/{total}: {prospect.company_name[:40]}...")

            enrichment = self.enrich_prospect(prospect, sources=sources)
            results.append(enrichment)

        if progress_callback:
            progress_callback(100, f"Enrichment complete for {total} prospects")

        return results
