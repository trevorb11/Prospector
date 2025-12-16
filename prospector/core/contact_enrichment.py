"""
Contact enrichment module for phone, email, and LinkedIn data.

This module provides integrations with various contact enrichment APIs
to enhance prospect records with verified contact information.

Supported sources:
- Hunter.io: Email finder and verifier
- Apollo.io: Contact database with LinkedIn data
- Clearbit: Company enrichment
- Google Places: Business phone numbers
- Proxycurl: LinkedIn profile data (authorized API)
"""

import os
import re
import json
import time
import hashlib
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
import urllib.request
import urllib.parse
import urllib.error

logger = logging.getLogger(__name__)


@dataclass
class ContactInfo:
    """Standardized contact information."""
    # Email data
    emails: List[Dict[str, Any]] = field(default_factory=list)
    primary_email: Optional[str] = None
    email_confidence: float = 0.0

    # Phone data
    phones: List[Dict[str, Any]] = field(default_factory=list)
    primary_phone: Optional[str] = None
    phone_type: Optional[str] = None  # mobile, landline, voip

    # LinkedIn data
    linkedin_url: Optional[str] = None
    linkedin_company_url: Optional[str] = None
    linkedin_employees: List[Dict[str, Any]] = field(default_factory=list)

    # Decision makers
    decision_makers: List[Dict[str, Any]] = field(default_factory=list)

    # Company data
    company_domain: Optional[str] = None
    company_website: Optional[str] = None
    company_description: Optional[str] = None
    company_industry: Optional[str] = None
    employee_count_range: Optional[str] = None
    annual_revenue_range: Optional[str] = None

    # Social profiles
    social_profiles: Dict[str, str] = field(default_factory=dict)

    # Enrichment metadata
    enriched_at: datetime = field(default_factory=datetime.now)
    sources_used: List[str] = field(default_factory=list)
    confidence_score: float = 0.0


class EnrichmentCache:
    """
    File-based cache for enrichment results.

    Caches API responses to reduce costs and improve performance.
    """

    def __init__(self, cache_dir: str = ".prospector_cache", ttl_hours: int = 168):
        """
        Initialize cache.

        Args:
            cache_dir: Directory for cache files
            ttl_hours: Cache time-to-live in hours (default 7 days)
        """
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(exist_ok=True)
        self.ttl = timedelta(hours=ttl_hours)

    def _get_cache_key(self, source: str, identifier: str) -> str:
        """Generate cache key from source and identifier."""
        key = f"{source}:{identifier}"
        return hashlib.md5(key.encode()).hexdigest()

    def _get_cache_path(self, cache_key: str) -> Path:
        """Get path to cache file."""
        return self.cache_dir / f"{cache_key}.json"

    def get(self, source: str, identifier: str) -> Optional[Dict[str, Any]]:
        """
        Get cached result if valid.

        Args:
            source: API source name
            identifier: Company/contact identifier

        Returns:
            Cached data or None if not found/expired
        """
        cache_key = self._get_cache_key(source, identifier)
        cache_path = self._get_cache_path(cache_key)

        if not cache_path.exists():
            return None

        try:
            with open(cache_path, 'r') as f:
                cached = json.load(f)

            cached_time = datetime.fromisoformat(cached['cached_at'])
            if datetime.now() - cached_time > self.ttl:
                cache_path.unlink()  # Remove expired cache
                return None

            return cached['data']
        except (json.JSONDecodeError, KeyError, ValueError):
            return None

    def set(self, source: str, identifier: str, data: Dict[str, Any]) -> None:
        """
        Cache enrichment result.

        Args:
            source: API source name
            identifier: Company/contact identifier
            data: Data to cache
        """
        cache_key = self._get_cache_key(source, identifier)
        cache_path = self._get_cache_path(cache_key)

        cache_entry = {
            'cached_at': datetime.now().isoformat(),
            'source': source,
            'identifier': identifier,
            'data': data
        }

        with open(cache_path, 'w') as f:
            json.dump(cache_entry, f)

    def clear(self, older_than_hours: Optional[int] = None) -> int:
        """
        Clear cache entries.

        Args:
            older_than_hours: Only clear entries older than this (None = all)

        Returns:
            Number of entries cleared
        """
        cleared = 0
        cutoff = datetime.now() - timedelta(hours=older_than_hours) if older_than_hours else None

        for cache_file in self.cache_dir.glob("*.json"):
            try:
                if cutoff:
                    with open(cache_file, 'r') as f:
                        cached = json.load(f)
                    cached_time = datetime.fromisoformat(cached['cached_at'])
                    if cached_time > cutoff:
                        continue

                cache_file.unlink()
                cleared += 1
            except Exception:
                continue

        return cleared


class RateLimiter:
    """
    Rate limiter with exponential backoff.

    Ensures API calls stay within rate limits.
    """

    def __init__(self, calls_per_minute: int = 60, burst_limit: int = 10):
        """
        Initialize rate limiter.

        Args:
            calls_per_minute: Maximum calls per minute
            burst_limit: Maximum burst of calls
        """
        self.calls_per_minute = calls_per_minute
        self.burst_limit = burst_limit
        self.calls: List[float] = []
        self.backoff_until: Optional[float] = None

    def wait_if_needed(self) -> None:
        """Wait if rate limit is approached."""
        now = time.time()

        # Check if we're in backoff period
        if self.backoff_until and now < self.backoff_until:
            sleep_time = self.backoff_until - now
            logger.debug(f"Rate limit backoff: sleeping {sleep_time:.1f}s")
            time.sleep(sleep_time)
            self.backoff_until = None

        # Remove old calls (older than 1 minute)
        self.calls = [t for t in self.calls if now - t < 60]

        # Check if at limit
        if len(self.calls) >= self.calls_per_minute:
            sleep_time = 60 - (now - self.calls[0])
            if sleep_time > 0:
                logger.debug(f"Rate limit reached: sleeping {sleep_time:.1f}s")
                time.sleep(sleep_time)

        # Check burst limit
        recent_calls = [t for t in self.calls if now - t < 1]
        if len(recent_calls) >= self.burst_limit:
            time.sleep(1.0 / self.burst_limit)

        self.calls.append(time.time())

    def backoff(self, seconds: float) -> None:
        """Set backoff period after rate limit error."""
        self.backoff_until = time.time() + seconds


class EnrichmentProvider(ABC):
    """Abstract base class for enrichment providers."""

    def __init__(self, api_key: Optional[str] = None, cache: Optional[EnrichmentCache] = None):
        self.api_key = api_key
        self.cache = cache or EnrichmentCache()
        self.rate_limiter = RateLimiter()

    @abstractmethod
    def get_name(self) -> str:
        """Return provider name."""
        pass

    @abstractmethod
    def enrich(self, company_name: str, domain: Optional[str] = None,
               city: Optional[str] = None, state: Optional[str] = None) -> Dict[str, Any]:
        """
        Enrich a company/contact.

        Args:
            company_name: Company name to enrich
            domain: Company domain if known
            city: City location
            state: State location

        Returns:
            Enrichment data dictionary
        """
        pass

    def _make_request(self, url: str, headers: Optional[Dict[str, str]] = None,
                      data: Optional[Dict[str, Any]] = None, method: str = "GET") -> Dict[str, Any]:
        """
        Make HTTP request with rate limiting.

        Args:
            url: Request URL
            headers: Request headers
            data: Request data (for POST)
            method: HTTP method

        Returns:
            Response JSON
        """
        self.rate_limiter.wait_if_needed()

        headers = headers or {}
        headers['User-Agent'] = 'Prospector/1.0'

        try:
            if data and method == "POST":
                req_data = json.dumps(data).encode('utf-8')
                headers['Content-Type'] = 'application/json'
            else:
                req_data = None

            req = urllib.request.Request(url, data=req_data, headers=headers, method=method)

            with urllib.request.urlopen(req, timeout=30) as response:
                return json.loads(response.read().decode('utf-8'))

        except urllib.error.HTTPError as e:
            if e.code == 429:  # Rate limited
                self.rate_limiter.backoff(60)
                raise
            raise
        except Exception as e:
            logger.error(f"Request failed: {e}")
            raise


class HunterProvider(EnrichmentProvider):
    """
    Hunter.io email finder integration.

    Finds email addresses associated with a domain.
    API docs: https://hunter.io/api-documentation
    """

    def __init__(self, api_key: Optional[str] = None, **kwargs):
        api_key = api_key or os.environ.get('HUNTER_API_KEY')
        super().__init__(api_key=api_key, **kwargs)
        self.base_url = "https://api.hunter.io/v2"

    def get_name(self) -> str:
        return "hunter"

    def enrich(self, company_name: str, domain: Optional[str] = None,
               city: Optional[str] = None, state: Optional[str] = None) -> Dict[str, Any]:
        """Find emails for a company domain."""
        if not self.api_key:
            return {"error": "No API key configured", "emails": []}

        # Check cache first
        cache_key = domain or company_name
        cached = self.cache.get(self.get_name(), cache_key)
        if cached:
            return cached

        result = {"emails": [], "domain": domain}

        try:
            # If no domain, try to find it
            if not domain:
                domain = self._find_domain(company_name)
                result["domain"] = domain

            if domain:
                # Domain search for emails
                url = f"{self.base_url}/domain-search?domain={domain}&api_key={self.api_key}"
                response = self._make_request(url)

                if response.get("data"):
                    data = response["data"]
                    result["emails"] = [
                        {
                            "email": e.get("value"),
                            "type": e.get("type"),
                            "confidence": e.get("confidence", 0),
                            "first_name": e.get("first_name"),
                            "last_name": e.get("last_name"),
                            "position": e.get("position"),
                            "department": e.get("department"),
                            "linkedin": e.get("linkedin"),
                            "twitter": e.get("twitter"),
                            "phone_number": e.get("phone_number")
                        }
                        for e in data.get("emails", [])
                    ]
                    result["organization"] = data.get("organization")
                    result["pattern"] = data.get("pattern")

            self.cache.set(self.get_name(), cache_key, result)

        except Exception as e:
            logger.error(f"Hunter enrichment failed: {e}")
            result["error"] = str(e)

        return result

    def _find_domain(self, company_name: str) -> Optional[str]:
        """Find domain for a company name."""
        try:
            encoded_name = urllib.parse.quote(company_name)
            url = f"{self.base_url}/domain-search?company={encoded_name}&api_key={self.api_key}"
            response = self._make_request(url)

            if response.get("data", {}).get("domain"):
                return response["data"]["domain"]
        except Exception:
            pass
        return None

    def verify_email(self, email: str) -> Dict[str, Any]:
        """Verify an email address."""
        if not self.api_key:
            return {"error": "No API key configured"}

        try:
            url = f"{self.base_url}/email-verifier?email={email}&api_key={self.api_key}"
            response = self._make_request(url)
            return response.get("data", {})
        except Exception as e:
            return {"error": str(e)}


class ApolloProvider(EnrichmentProvider):
    """
    Apollo.io contact database integration.

    Provides contact info including LinkedIn profiles.
    API docs: https://apolloio.github.io/apollo-api-docs/
    """

    def __init__(self, api_key: Optional[str] = None, **kwargs):
        api_key = api_key or os.environ.get('APOLLO_API_KEY')
        super().__init__(api_key=api_key, **kwargs)
        self.base_url = "https://api.apollo.io/v1"

    def get_name(self) -> str:
        return "apollo"

    def enrich(self, company_name: str, domain: Optional[str] = None,
               city: Optional[str] = None, state: Optional[str] = None) -> Dict[str, Any]:
        """Enrich company with contacts and LinkedIn data."""
        if not self.api_key:
            return {"error": "No API key configured", "contacts": []}

        cache_key = f"{company_name}:{state or ''}"
        cached = self.cache.get(self.get_name(), cache_key)
        if cached:
            return cached

        result = {
            "contacts": [],
            "company": {},
            "linkedin_url": None
        }

        try:
            # Search for organization
            org_data = self._search_organization(company_name, domain, city, state)

            if org_data:
                result["company"] = {
                    "name": org_data.get("name"),
                    "domain": org_data.get("primary_domain"),
                    "linkedin_url": org_data.get("linkedin_url"),
                    "phone": org_data.get("phone"),
                    "industry": org_data.get("industry"),
                    "employee_count": org_data.get("estimated_num_employees"),
                    "annual_revenue": org_data.get("annual_revenue"),
                    "description": org_data.get("short_description")
                }
                result["linkedin_url"] = org_data.get("linkedin_url")

                # Get contacts/decision makers
                if org_data.get("id"):
                    contacts = self._get_contacts(org_data["id"])
                    result["contacts"] = contacts

            self.cache.set(self.get_name(), cache_key, result)

        except Exception as e:
            logger.error(f"Apollo enrichment failed: {e}")
            result["error"] = str(e)

        return result

    def _search_organization(self, company_name: str, domain: Optional[str],
                            city: Optional[str], state: Optional[str]) -> Optional[Dict[str, Any]]:
        """Search for organization in Apollo."""
        try:
            headers = {
                "Content-Type": "application/json",
                "Cache-Control": "no-cache",
                "X-Api-Key": self.api_key
            }

            payload = {
                "q_organization_name": company_name,
                "per_page": 1
            }

            if domain:
                payload["q_organization_domains"] = domain
            if state:
                payload["organization_locations"] = [state]

            url = f"{self.base_url}/mixed_companies/search"
            response = self._make_request(url, headers=headers, data=payload, method="POST")

            organizations = response.get("organizations", [])
            if organizations:
                return organizations[0]

        except Exception as e:
            logger.error(f"Apollo org search failed: {e}")

        return None

    def _get_contacts(self, organization_id: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Get contacts for an organization."""
        contacts = []

        try:
            headers = {
                "Content-Type": "application/json",
                "Cache-Control": "no-cache",
                "X-Api-Key": self.api_key
            }

            # Search for decision makers (owners, executives, managers)
            payload = {
                "organization_ids": [organization_id],
                "person_seniorities": ["owner", "founder", "c_suite", "vp", "director", "manager"],
                "per_page": limit
            }

            url = f"{self.base_url}/mixed_people/search"
            response = self._make_request(url, headers=headers, data=payload, method="POST")

            for person in response.get("people", []):
                contacts.append({
                    "name": person.get("name"),
                    "first_name": person.get("first_name"),
                    "last_name": person.get("last_name"),
                    "title": person.get("title"),
                    "email": person.get("email"),
                    "phone": person.get("sanitized_phone"),
                    "linkedin_url": person.get("linkedin_url"),
                    "seniority": person.get("seniority"),
                    "departments": person.get("departments", [])
                })

        except Exception as e:
            logger.error(f"Apollo contacts search failed: {e}")

        return contacts


class GooglePlacesProvider(EnrichmentProvider):
    """
    Google Places API for business phone numbers.

    Good for local businesses like restaurants and auto dealers.
    """

    def __init__(self, api_key: Optional[str] = None, **kwargs):
        api_key = api_key or os.environ.get('GOOGLE_PLACES_API_KEY')
        super().__init__(api_key=api_key, **kwargs)
        self.base_url = "https://maps.googleapis.com/maps/api/place"

    def get_name(self) -> str:
        return "google_places"

    def enrich(self, company_name: str, domain: Optional[str] = None,
               city: Optional[str] = None, state: Optional[str] = None) -> Dict[str, Any]:
        """Find business details from Google Places."""
        if not self.api_key:
            return {"error": "No API key configured"}

        cache_key = f"{company_name}:{city or ''}:{state or ''}"
        cached = self.cache.get(self.get_name(), cache_key)
        if cached:
            return cached

        result = {
            "phone": None,
            "website": None,
            "address": None,
            "rating": None,
            "reviews_count": None,
            "place_id": None
        }

        try:
            # Build search query
            query = company_name
            if city:
                query += f" {city}"
            if state:
                query += f" {state}"

            # Find place
            encoded_query = urllib.parse.quote(query)
            search_url = f"{self.base_url}/findplacefromtext/json?input={encoded_query}&inputtype=textquery&fields=place_id,name,formatted_address&key={self.api_key}"

            search_response = self._make_request(search_url)
            candidates = search_response.get("candidates", [])

            if candidates:
                place_id = candidates[0].get("place_id")
                result["place_id"] = place_id

                # Get place details
                details_url = f"{self.base_url}/details/json?place_id={place_id}&fields=formatted_phone_number,international_phone_number,website,rating,user_ratings_total,formatted_address,opening_hours&key={self.api_key}"

                details_response = self._make_request(details_url)
                details = details_response.get("result", {})

                result["phone"] = details.get("formatted_phone_number")
                result["international_phone"] = details.get("international_phone_number")
                result["website"] = details.get("website")
                result["address"] = details.get("formatted_address")
                result["rating"] = details.get("rating")
                result["reviews_count"] = details.get("user_ratings_total")
                result["hours"] = details.get("opening_hours", {}).get("weekday_text", [])

            self.cache.set(self.get_name(), cache_key, result)

        except Exception as e:
            logger.error(f"Google Places enrichment failed: {e}")
            result["error"] = str(e)

        return result


class ClearbitProvider(EnrichmentProvider):
    """
    Clearbit company enrichment.

    Provides comprehensive company data.
    API docs: https://clearbit.com/docs
    """

    def __init__(self, api_key: Optional[str] = None, **kwargs):
        api_key = api_key or os.environ.get('CLEARBIT_API_KEY')
        super().__init__(api_key=api_key, **kwargs)
        self.base_url = "https://company.clearbit.com/v2"

    def get_name(self) -> str:
        return "clearbit"

    def enrich(self, company_name: str, domain: Optional[str] = None,
               city: Optional[str] = None, state: Optional[str] = None) -> Dict[str, Any]:
        """Enrich company data from Clearbit."""
        if not self.api_key:
            return {"error": "No API key configured"}

        if not domain:
            # Clearbit requires a domain
            return {"error": "Domain required for Clearbit"}

        cached = self.cache.get(self.get_name(), domain)
        if cached:
            return cached

        result = {}

        try:
            import base64
            auth = base64.b64encode(f"{self.api_key}:".encode()).decode()
            headers = {"Authorization": f"Basic {auth}"}

            url = f"{self.base_url}/companies/find?domain={domain}"
            response = self._make_request(url, headers=headers)

            result = {
                "name": response.get("name"),
                "domain": response.get("domain"),
                "description": response.get("description"),
                "industry": response.get("category", {}).get("industry"),
                "sector": response.get("category", {}).get("sector"),
                "employee_count": response.get("metrics", {}).get("employees"),
                "employee_range": response.get("metrics", {}).get("employeesRange"),
                "annual_revenue": response.get("metrics", {}).get("estimatedAnnualRevenue"),
                "phone": response.get("phone"),
                "linkedin_url": response.get("linkedin", {}).get("handle"),
                "twitter_url": response.get("twitter", {}).get("handle"),
                "facebook_url": response.get("facebook", {}).get("handle"),
                "founded_year": response.get("foundedYear"),
                "location": {
                    "city": response.get("geo", {}).get("city"),
                    "state": response.get("geo", {}).get("state"),
                    "country": response.get("geo", {}).get("country")
                },
                "tech_stack": response.get("tech", [])
            }

            self.cache.set(self.get_name(), domain, result)

        except Exception as e:
            logger.error(f"Clearbit enrichment failed: {e}")
            result["error"] = str(e)

        return result


class ProxycurlProvider(EnrichmentProvider):
    """
    Proxycurl LinkedIn data provider.

    Authorized API for LinkedIn profile and company data.
    API docs: https://nubela.co/proxycurl/docs
    """

    def __init__(self, api_key: Optional[str] = None, **kwargs):
        api_key = api_key or os.environ.get('PROXYCURL_API_KEY')
        super().__init__(api_key=api_key, **kwargs)
        self.base_url = "https://nubela.co/proxycurl/api"

    def get_name(self) -> str:
        return "proxycurl"

    def enrich(self, company_name: str, domain: Optional[str] = None,
               city: Optional[str] = None, state: Optional[str] = None) -> Dict[str, Any]:
        """Enrich with LinkedIn company data."""
        if not self.api_key:
            return {"error": "No API key configured"}

        cache_key = domain or company_name
        cached = self.cache.get(self.get_name(), cache_key)
        if cached:
            return cached

        result = {
            "linkedin_url": None,
            "company": {},
            "employees": []
        }

        try:
            headers = {"Authorization": f"Bearer {self.api_key}"}

            # Search for company
            if domain:
                search_url = f"{self.base_url}/linkedin/company/resolve?company_domain={domain}"
            else:
                encoded_name = urllib.parse.quote(company_name)
                location = f"{city}, {state}" if city and state else state or ""
                search_url = f"{self.base_url}/linkedin/company/resolve?company_name={encoded_name}"
                if location:
                    search_url += f"&company_location={urllib.parse.quote(location)}"

            resolve_response = self._make_request(search_url, headers=headers)
            linkedin_url = resolve_response.get("url")

            if linkedin_url:
                result["linkedin_url"] = linkedin_url

                # Get company profile
                encoded_url = urllib.parse.quote(linkedin_url)
                profile_url = f"{self.base_url}/linkedin/company?url={encoded_url}"

                profile = self._make_request(profile_url, headers=headers)

                result["company"] = {
                    "name": profile.get("name"),
                    "description": profile.get("description"),
                    "website": profile.get("website"),
                    "industry": profile.get("industry"),
                    "company_size": profile.get("company_size"),
                    "company_size_range": profile.get("company_size_on_linkedin"),
                    "headquarters": profile.get("hq", {}),
                    "founded_year": profile.get("founded_year"),
                    "specialties": profile.get("specialities", []),
                    "follower_count": profile.get("follower_count")
                }

                # Get employee search for decision makers
                employees = self._search_employees(linkedin_url, headers)
                result["employees"] = employees

            self.cache.set(self.get_name(), cache_key, result)

        except Exception as e:
            logger.error(f"Proxycurl enrichment failed: {e}")
            result["error"] = str(e)

        return result

    def _search_employees(self, company_linkedin_url: str, headers: Dict[str, str],
                          limit: int = 5) -> List[Dict[str, Any]]:
        """Search for employees at a company."""
        employees = []

        try:
            encoded_url = urllib.parse.quote(company_linkedin_url)
            # Search for decision makers
            search_url = f"{self.base_url}/linkedin/company/employees/?url={encoded_url}&role_search=owner%20founder%20ceo%20president%20director%20manager&page_size={limit}"

            response = self._make_request(search_url, headers=headers)

            for emp in response.get("employees", []):
                if emp.get("profile"):
                    profile = emp["profile"]
                    employees.append({
                        "name": profile.get("full_name"),
                        "title": profile.get("occupation"),
                        "linkedin_url": profile.get("profile_url"),
                        "headline": profile.get("headline"),
                        "city": profile.get("city"),
                        "state": profile.get("state")
                    })

        except Exception as e:
            logger.error(f"Employee search failed: {e}")

        return employees

    def get_person_profile(self, linkedin_url: str) -> Dict[str, Any]:
        """Get detailed LinkedIn person profile."""
        if not self.api_key:
            return {"error": "No API key configured"}

        cached = self.cache.get(f"{self.get_name()}_person", linkedin_url)
        if cached:
            return cached

        try:
            headers = {"Authorization": f"Bearer {self.api_key}"}
            encoded_url = urllib.parse.quote(linkedin_url)
            url = f"{self.base_url}/v2/linkedin?url={encoded_url}"

            profile = self._make_request(url, headers=headers)

            result = {
                "name": profile.get("full_name"),
                "first_name": profile.get("first_name"),
                "last_name": profile.get("last_name"),
                "headline": profile.get("headline"),
                "summary": profile.get("summary"),
                "city": profile.get("city"),
                "state": profile.get("state"),
                "country": profile.get("country_full_name"),
                "experiences": profile.get("experiences", []),
                "education": profile.get("education", []),
                "personal_emails": profile.get("personal_emails", []),
                "personal_numbers": profile.get("personal_numbers", [])
            }

            self.cache.set(f"{self.get_name()}_person", linkedin_url, result)
            return result

        except Exception as e:
            logger.error(f"Person profile lookup failed: {e}")
            return {"error": str(e)}


class ContactEnricher:
    """
    Main contact enrichment orchestrator.

    Combines multiple providers to get comprehensive contact data.
    """

    def __init__(self, providers: Optional[List[str]] = None,
                 api_keys: Optional[Dict[str, str]] = None,
                 cache: Optional[EnrichmentCache] = None,
                 max_workers: int = 3):
        """
        Initialize contact enricher.

        Args:
            providers: List of provider names to use (default: all available)
            api_keys: Dict of API keys by provider name
            cache: Shared cache instance
            max_workers: Max parallel provider calls
        """
        self.cache = cache or EnrichmentCache()
        self.max_workers = max_workers
        self.api_keys = api_keys or {}

        # Initialize providers
        available_providers = {
            "hunter": HunterProvider,
            "apollo": ApolloProvider,
            "google_places": GooglePlacesProvider,
            "clearbit": ClearbitProvider,
            "proxycurl": ProxycurlProvider
        }

        self.providers: Dict[str, EnrichmentProvider] = {}

        providers_to_use = providers or list(available_providers.keys())
        for name in providers_to_use:
            if name in available_providers:
                api_key = self.api_keys.get(name)
                self.providers[name] = available_providers[name](
                    api_key=api_key,
                    cache=self.cache
                )

    def enrich(self, company_name: str, domain: Optional[str] = None,
               city: Optional[str] = None, state: Optional[str] = None,
               phone: Optional[str] = None,
               providers: Optional[List[str]] = None) -> ContactInfo:
        """
        Enrich a company with contact data from multiple sources.

        Args:
            company_name: Company name
            domain: Company website domain
            city: City location
            state: State location
            phone: Existing phone number
            providers: Specific providers to use (default: all)

        Returns:
            ContactInfo with enriched data
        """
        result = ContactInfo()
        providers_to_use = providers or list(self.providers.keys())

        # Run providers in parallel
        provider_results: Dict[str, Dict[str, Any]] = {}

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {}
            for name in providers_to_use:
                if name in self.providers:
                    future = executor.submit(
                        self.providers[name].enrich,
                        company_name, domain, city, state
                    )
                    futures[future] = name

            for future in as_completed(futures):
                name = futures[future]
                try:
                    provider_results[name] = future.result()
                    result.sources_used.append(name)
                except Exception as e:
                    logger.error(f"Provider {name} failed: {e}")

        # Merge results
        result = self._merge_results(result, provider_results, phone)
        result.enriched_at = datetime.now()

        return result

    def _merge_results(self, result: ContactInfo,
                       provider_results: Dict[str, Dict[str, Any]],
                       existing_phone: Optional[str] = None) -> ContactInfo:
        """Merge results from multiple providers."""

        all_emails = []
        all_phones = []
        all_contacts = []

        # Process each provider's results
        for provider, data in provider_results.items():
            if "error" in data:
                continue

            # Collect emails
            if provider == "hunter":
                for email in data.get("emails", []):
                    all_emails.append({
                        "email": email.get("email"),
                        "confidence": email.get("confidence", 0),
                        "type": email.get("type"),
                        "name": f"{email.get('first_name', '')} {email.get('last_name', '')}".strip(),
                        "title": email.get("position"),
                        "source": "hunter"
                    })
                    # Check if email has phone
                    if email.get("phone_number"):
                        all_phones.append({
                            "phone": email["phone_number"],
                            "source": "hunter",
                            "type": "work"
                        })

            # Collect from Apollo
            if provider == "apollo":
                company = data.get("company", {})
                if company.get("phone"):
                    all_phones.append({
                        "phone": company["phone"],
                        "source": "apollo",
                        "type": "main"
                    })
                if company.get("linkedin_url"):
                    result.linkedin_company_url = company["linkedin_url"]
                if company.get("domain"):
                    result.company_domain = company["domain"]
                if company.get("description"):
                    result.company_description = company["description"]
                if company.get("industry"):
                    result.company_industry = company["industry"]
                if company.get("employee_count"):
                    result.employee_count_range = str(company["employee_count"])
                if company.get("annual_revenue"):
                    result.annual_revenue_range = company["annual_revenue"]

                for contact in data.get("contacts", []):
                    all_contacts.append({
                        "name": contact.get("name"),
                        "title": contact.get("title"),
                        "email": contact.get("email"),
                        "phone": contact.get("phone"),
                        "linkedin_url": contact.get("linkedin_url"),
                        "seniority": contact.get("seniority"),
                        "source": "apollo"
                    })
                    if contact.get("email"):
                        all_emails.append({
                            "email": contact["email"],
                            "confidence": 80,
                            "name": contact.get("name"),
                            "title": contact.get("title"),
                            "source": "apollo"
                        })

            # Google Places
            if provider == "google_places":
                if data.get("phone"):
                    all_phones.append({
                        "phone": data["phone"],
                        "source": "google_places",
                        "type": "main",
                        "verified": True
                    })
                if data.get("website"):
                    result.company_website = data["website"]

            # Clearbit
            if provider == "clearbit":
                if data.get("phone"):
                    all_phones.append({
                        "phone": data["phone"],
                        "source": "clearbit",
                        "type": "main"
                    })
                if data.get("linkedin_url"):
                    result.social_profiles["linkedin"] = data["linkedin_url"]
                if data.get("twitter_url"):
                    result.social_profiles["twitter"] = data["twitter_url"]
                if data.get("facebook_url"):
                    result.social_profiles["facebook"] = data["facebook_url"]
                if data.get("employee_range"):
                    result.employee_count_range = data["employee_range"]
                if data.get("annual_revenue"):
                    result.annual_revenue_range = data["annual_revenue"]

            # Proxycurl
            if provider == "proxycurl":
                if data.get("linkedin_url"):
                    result.linkedin_company_url = data["linkedin_url"]

                company = data.get("company", {})
                if company.get("website"):
                    result.company_website = company["website"]
                if company.get("description"):
                    result.company_description = company["description"]

                for emp in data.get("employees", []):
                    all_contacts.append({
                        "name": emp.get("name"),
                        "title": emp.get("title"),
                        "linkedin_url": emp.get("linkedin_url"),
                        "source": "proxycurl"
                    })

        # Add existing phone if provided
        if existing_phone:
            all_phones.insert(0, {
                "phone": existing_phone,
                "source": "original",
                "type": "main"
            })

        # Deduplicate and rank emails
        seen_emails = set()
        unique_emails = []
        for email in sorted(all_emails, key=lambda x: x.get("confidence", 0), reverse=True):
            if email.get("email") and email["email"].lower() not in seen_emails:
                seen_emails.add(email["email"].lower())
                unique_emails.append(email)

        result.emails = unique_emails
        if unique_emails:
            result.primary_email = unique_emails[0]["email"]
            result.email_confidence = unique_emails[0].get("confidence", 0)

        # Deduplicate phones
        seen_phones = set()
        unique_phones = []
        for phone in all_phones:
            normalized = self._normalize_phone(phone.get("phone", ""))
            if normalized and normalized not in seen_phones:
                seen_phones.add(normalized)
                phone["phone"] = normalized
                unique_phones.append(phone)

        result.phones = unique_phones
        if unique_phones:
            result.primary_phone = unique_phones[0]["phone"]
            result.phone_type = unique_phones[0].get("type")

        # Deduplicate contacts/decision makers
        seen_contacts = set()
        unique_contacts = []
        for contact in all_contacts:
            key = contact.get("email") or contact.get("linkedin_url") or contact.get("name", "")
            if key and key not in seen_contacts:
                seen_contacts.add(key)
                unique_contacts.append(contact)

        result.decision_makers = unique_contacts[:10]  # Top 10
        result.linkedin_employees = [c for c in unique_contacts if c.get("linkedin_url")]

        # Calculate confidence score
        score = 0
        if result.primary_email:
            score += 30
        if result.primary_phone:
            score += 30
        if result.linkedin_company_url:
            score += 15
        if result.decision_makers:
            score += 15
        if result.company_website:
            score += 10

        result.confidence_score = min(score, 100)

        return result

    def _normalize_phone(self, phone: str) -> str:
        """Normalize phone number format."""
        if not phone:
            return ""

        # Remove non-digits
        digits = re.sub(r'\D', '', phone)

        # Handle US numbers
        if len(digits) == 10:
            return f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"
        elif len(digits) == 11 and digits[0] == '1':
            return f"({digits[1:4]}) {digits[4:7]}-{digits[7:]}"

        return phone  # Return original if can't normalize

    def enrich_batch(self, prospects: List[Dict[str, Any]],
                     name_field: str = "company_name",
                     domain_field: str = "domain",
                     city_field: str = "city",
                     state_field: str = "state",
                     phone_field: str = "phone",
                     progress_callback=None,
                     max_parallel: int = 5) -> List[Tuple[Dict[str, Any], ContactInfo]]:
        """
        Enrich a batch of prospects.

        Args:
            prospects: List of prospect dictionaries
            name_field: Field name for company name
            domain_field: Field name for domain
            city_field: Field name for city
            state_field: Field name for state
            phone_field: Field name for phone
            progress_callback: Optional callback(current, total)
            max_parallel: Maximum parallel enrichments

        Returns:
            List of tuples (original_prospect, ContactInfo)
        """
        results = []
        total = len(prospects)

        with ThreadPoolExecutor(max_workers=max_parallel) as executor:
            futures = {}

            for i, prospect in enumerate(prospects):
                future = executor.submit(
                    self.enrich,
                    company_name=prospect.get(name_field, ""),
                    domain=prospect.get(domain_field),
                    city=prospect.get(city_field),
                    state=prospect.get(state_field),
                    phone=prospect.get(phone_field)
                )
                futures[future] = (i, prospect)

            completed = 0
            for future in as_completed(futures):
                idx, prospect = futures[future]
                try:
                    contact_info = future.result()
                    results.append((prospect, contact_info))
                except Exception as e:
                    logger.error(f"Batch enrichment failed for {prospect.get(name_field)}: {e}")
                    results.append((prospect, ContactInfo()))

                completed += 1
                if progress_callback:
                    progress_callback(completed, total)

        # Sort by original order
        results.sort(key=lambda x: prospects.index(x[0]))
        return results


# Convenience function for quick enrichment
def enrich_contact(company_name: str, domain: Optional[str] = None,
                   city: Optional[str] = None, state: Optional[str] = None,
                   providers: Optional[List[str]] = None) -> ContactInfo:
    """
    Quick contact enrichment.

    Args:
        company_name: Company name
        domain: Company domain
        city: City location
        state: State location
        providers: Specific providers to use

    Returns:
        ContactInfo with enriched data
    """
    enricher = ContactEnricher(providers=providers)
    return enricher.enrich(company_name, domain, city, state)
