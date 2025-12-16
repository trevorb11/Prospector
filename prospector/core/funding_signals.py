"""
Funding signals detection module.

This module provides additional data sources and detection methods
to identify prospects who are likely to need financing soon.

Signal Sources:
- UCC filings (equipment liens about to expire)
- Job postings (growth/expansion signals)
- News monitoring (expansion announcements, new contracts)
- Business credit indicators
- Real estate/lease data
- SBA loan history
"""

import os
import re
import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed
import urllib.request
import urllib.parse

from .contact_enrichment import EnrichmentCache, RateLimiter

logger = logging.getLogger(__name__)


@dataclass
class FundingSignal:
    """A detected funding signal."""
    signal_type: str  # e.g., "ucc_expiring", "job_posting", "expansion_news"
    signal_name: str  # Human-readable name
    description: str  # Detailed description
    strength: str  # "high", "medium", "low"
    score_boost: int  # Points to add to prospect score
    source: str  # Data source name
    detected_at: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class FundingSignalReport:
    """Collection of funding signals for a prospect."""
    company_name: str
    signals: List[FundingSignal] = field(default_factory=list)
    total_score_boost: int = 0
    funding_likelihood: str = "unknown"  # high, medium, low, unknown
    funding_likelihood_score: float = 0.0
    recommended_timing: Optional[str] = None
    recommended_products: List[str] = field(default_factory=list)
    sources_checked: List[str] = field(default_factory=list)
    checked_at: datetime = field(default_factory=datetime.now)

    def add_signal(self, signal: FundingSignal) -> None:
        """Add a signal and update totals."""
        self.signals.append(signal)
        self.total_score_boost += signal.score_boost
        self._update_likelihood()

    def _update_likelihood(self) -> None:
        """Update funding likelihood based on signals."""
        high_signals = sum(1 for s in self.signals if s.strength == "high")
        med_signals = sum(1 for s in self.signals if s.strength == "medium")

        score = (high_signals * 30) + (med_signals * 15)
        self.funding_likelihood_score = min(score, 100)

        if score >= 60 or high_signals >= 2:
            self.funding_likelihood = "high"
        elif score >= 30 or high_signals >= 1:
            self.funding_likelihood = "medium"
        elif self.signals:
            self.funding_likelihood = "low"
        else:
            self.funding_likelihood = "unknown"


class SignalDetector(ABC):
    """Abstract base class for signal detectors."""

    def __init__(self, api_key: Optional[str] = None, cache: Optional[EnrichmentCache] = None):
        self.api_key = api_key
        self.cache = cache or EnrichmentCache()
        self.rate_limiter = RateLimiter(calls_per_minute=30)

    @abstractmethod
    def get_name(self) -> str:
        """Return detector name."""
        pass

    @abstractmethod
    def detect(self, company_name: str, state: Optional[str] = None,
               industry: Optional[str] = None, **kwargs) -> List[FundingSignal]:
        """Detect funding signals for a company."""
        pass

    def _make_request(self, url: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        """Make HTTP request with rate limiting."""
        self.rate_limiter.wait_if_needed()

        headers = headers or {}
        headers['User-Agent'] = 'Prospector/1.0'

        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=30) as response:
                return json.loads(response.read().decode('utf-8'))
        except Exception as e:
            logger.error(f"Request failed: {e}")
            raise


class UCCFilingDetector(SignalDetector):
    """
    Detect UCC filing signals.

    UCC-1 filings indicate equipment liens. Filings about to expire
    or recently filed can indicate financing needs.

    Uses state secretary of state data and commercial data providers.
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # State SOS APIs vary - this uses common commercial data APIs
        self.api_key = self.api_key or os.environ.get('UCC_API_KEY')

    def get_name(self) -> str:
        return "ucc_filings"

    def detect(self, company_name: str, state: Optional[str] = None,
               industry: Optional[str] = None, **kwargs) -> List[FundingSignal]:
        """Detect UCC-related funding signals."""
        signals = []

        # Check cache
        cache_key = f"ucc:{company_name}:{state or ''}"
        cached = self.cache.get(self.get_name(), cache_key)
        if cached:
            return [FundingSignal(**s) for s in cached]

        try:
            filings = self._search_filings(company_name, state)

            for filing in filings:
                # Check for expiring liens (typically 5 years)
                if filing.get("expiration_date"):
                    exp_date = datetime.fromisoformat(filing["expiration_date"])
                    days_to_expiry = (exp_date - datetime.now()).days

                    if 0 < days_to_expiry <= 180:
                        signals.append(FundingSignal(
                            signal_type="ucc_expiring",
                            signal_name="Equipment Lien Expiring",
                            description=f"UCC filing expiring in {days_to_expiry} days - may need refinancing",
                            strength="high" if days_to_expiry <= 90 else "medium",
                            score_boost=25 if days_to_expiry <= 90 else 15,
                            source=self.get_name(),
                            metadata={
                                "filing_number": filing.get("filing_number"),
                                "secured_party": filing.get("secured_party"),
                                "collateral": filing.get("collateral_description"),
                                "expiration_date": filing["expiration_date"],
                                "days_to_expiry": days_to_expiry
                            }
                        ))

                # Check for recent filings (new equipment = growth)
                if filing.get("filing_date"):
                    file_date = datetime.fromisoformat(filing["filing_date"])
                    days_since_filing = (datetime.now() - file_date).days

                    if days_since_filing <= 90:
                        signals.append(FundingSignal(
                            signal_type="ucc_recent",
                            signal_name="Recent Equipment Financing",
                            description="Recently obtained equipment financing - actively investing in growth",
                            strength="medium",
                            score_boost=10,
                            source=self.get_name(),
                            metadata={
                                "filing_date": filing["filing_date"],
                                "collateral": filing.get("collateral_description")
                            }
                        ))

            # Cache results
            self.cache.set(self.get_name(), cache_key,
                          [{"signal_type": s.signal_type, "signal_name": s.signal_name,
                            "description": s.description, "strength": s.strength,
                            "score_boost": s.score_boost, "source": s.source,
                            "metadata": s.metadata} for s in signals])

        except Exception as e:
            logger.error(f"UCC detection failed: {e}")

        return signals

    def _search_filings(self, company_name: str, state: Optional[str]) -> List[Dict[str, Any]]:
        """Search for UCC filings. Override for actual API integration."""
        # This is a placeholder - actual implementation would use:
        # - State Secretary of State APIs
        # - Commercial data providers (D&B, LexisNexis, etc.)
        return []


class JobPostingDetector(SignalDetector):
    """
    Detect job posting signals indicating growth.

    Hiring patterns can indicate:
    - Business expansion
    - New locations/facilities
    - Equipment needs (drivers = trucks, mechanics = equipment)
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.api_key = self.api_key or os.environ.get('JOBS_API_KEY')

    def get_name(self) -> str:
        return "job_postings"

    def detect(self, company_name: str, state: Optional[str] = None,
               industry: Optional[str] = None, **kwargs) -> List[FundingSignal]:
        """Detect growth signals from job postings."""
        signals = []

        cache_key = f"jobs:{company_name}:{state or ''}"
        cached = self.cache.get(self.get_name(), cache_key)
        if cached:
            return [FundingSignal(**s) for s in cached]

        try:
            postings = self._search_jobs(company_name, state)

            if not postings:
                return signals

            # Analyze posting patterns
            job_count = len(postings)
            job_titles = [p.get("title", "").lower() for p in postings]

            # High growth signal: Many openings
            if job_count >= 10:
                signals.append(FundingSignal(
                    signal_type="hiring_surge",
                    signal_name="Rapid Hiring",
                    description=f"Company has {job_count} open positions - significant growth phase",
                    strength="high",
                    score_boost=25,
                    source=self.get_name(),
                    metadata={"job_count": job_count}
                ))
            elif job_count >= 5:
                signals.append(FundingSignal(
                    signal_type="hiring_growth",
                    signal_name="Active Hiring",
                    description=f"Company has {job_count} open positions - growth mode",
                    strength="medium",
                    score_boost=15,
                    source=self.get_name(),
                    metadata={"job_count": job_count}
                ))

            # Industry-specific signals
            driver_jobs = sum(1 for t in job_titles if any(
                w in t for w in ['driver', 'cdl', 'trucker', 'delivery']))
            if driver_jobs >= 3:
                signals.append(FundingSignal(
                    signal_type="fleet_expansion",
                    signal_name="Fleet Expansion",
                    description=f"Hiring {driver_jobs} drivers - likely needs additional trucks",
                    strength="high",
                    score_boost=20,
                    source=self.get_name(),
                    metadata={"driver_openings": driver_jobs}
                ))

            mechanic_jobs = sum(1 for t in job_titles if any(
                w in t for w in ['mechanic', 'technician', 'service']))
            if mechanic_jobs >= 2:
                signals.append(FundingSignal(
                    signal_type="service_expansion",
                    signal_name="Service Capacity Expansion",
                    description=f"Hiring {mechanic_jobs} service staff - may need equipment",
                    strength="medium",
                    score_boost=15,
                    source=self.get_name(),
                    metadata={"service_openings": mechanic_jobs}
                ))

            # Management hiring = strategic growth
            mgmt_jobs = sum(1 for t in job_titles if any(
                w in t for w in ['manager', 'director', 'vp', 'executive', 'chief']))
            if mgmt_jobs >= 2:
                signals.append(FundingSignal(
                    signal_type="leadership_expansion",
                    signal_name="Leadership Team Growth",
                    description="Hiring leadership positions - preparing for significant expansion",
                    strength="medium",
                    score_boost=15,
                    source=self.get_name(),
                    metadata={"leadership_openings": mgmt_jobs}
                ))

            # Cache results
            self.cache.set(self.get_name(), cache_key,
                          [{"signal_type": s.signal_type, "signal_name": s.signal_name,
                            "description": s.description, "strength": s.strength,
                            "score_boost": s.score_boost, "source": s.source,
                            "metadata": s.metadata} for s in signals])

        except Exception as e:
            logger.error(f"Job posting detection failed: {e}")

        return signals

    def _search_jobs(self, company_name: str, state: Optional[str]) -> List[Dict[str, Any]]:
        """Search for job postings."""
        # Uses public job APIs or commercial data
        # Example: Indeed API, LinkedIn Jobs, Google Jobs API
        postings = []

        try:
            # Try Google Custom Search for job postings
            google_api_key = os.environ.get('GOOGLE_API_KEY')
            google_cx = os.environ.get('GOOGLE_SEARCH_CX')

            if google_api_key and google_cx:
                query = f'"{company_name}" jobs hiring'
                if state:
                    query += f' {state}'

                encoded_query = urllib.parse.quote(query)
                url = f"https://www.googleapis.com/customsearch/v1?key={google_api_key}&cx={google_cx}&q={encoded_query}"

                response = self._make_request(url)
                items = response.get("items", [])

                for item in items[:10]:
                    title = item.get("title", "")
                    # Extract job title from search result
                    if any(w in title.lower() for w in ['job', 'hiring', 'career', 'position']):
                        postings.append({
                            "title": title,
                            "url": item.get("link"),
                            "snippet": item.get("snippet")
                        })

        except Exception as e:
            logger.error(f"Job search failed: {e}")

        return postings


class NewsSignalDetector(SignalDetector):
    """
    Detect funding signals from news and press releases.

    News signals include:
    - Expansion announcements
    - New contracts/customers
    - Awards and certifications
    - Leadership changes
    - Funding rounds
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.api_key = self.api_key or os.environ.get('NEWS_API_KEY')

    def get_name(self) -> str:
        return "news"

    def detect(self, company_name: str, state: Optional[str] = None,
               industry: Optional[str] = None, **kwargs) -> List[FundingSignal]:
        """Detect funding signals from news."""
        signals = []

        cache_key = f"news:{company_name}"
        cached = self.cache.get(self.get_name(), cache_key)
        if cached:
            return [FundingSignal(**s) for s in cached]

        try:
            articles = self._search_news(company_name)

            for article in articles:
                title = article.get("title", "").lower()
                description = article.get("description", "").lower()
                content = f"{title} {description}"

                # Expansion signals
                if any(w in content for w in ['expand', 'expansion', 'new location',
                                               'open new', 'growing', 'growth']):
                    signals.append(FundingSignal(
                        signal_type="expansion_news",
                        signal_name="Expansion Announcement",
                        description="Company announced expansion plans",
                        strength="high",
                        score_boost=25,
                        source=self.get_name(),
                        metadata={
                            "article_title": article.get("title"),
                            "published": article.get("publishedAt"),
                            "url": article.get("url")
                        }
                    ))

                # New contract signals
                if any(w in content for w in ['contract', 'awarded', 'partnership',
                                               'deal', 'agreement', 'customer']):
                    signals.append(FundingSignal(
                        signal_type="new_contract",
                        signal_name="New Business Contract",
                        description="Company won new contract or partnership",
                        strength="medium",
                        score_boost=15,
                        source=self.get_name(),
                        metadata={
                            "article_title": article.get("title"),
                            "url": article.get("url")
                        }
                    ))

                # Equipment/facility news
                if any(w in content for w in ['equipment', 'facility', 'fleet',
                                               'vehicle', 'machinery', 'upgrade']):
                    signals.append(FundingSignal(
                        signal_type="equipment_news",
                        signal_name="Equipment/Facility Investment",
                        description="Company investing in equipment or facilities",
                        strength="high",
                        score_boost=20,
                        source=self.get_name(),
                        metadata={
                            "article_title": article.get("title"),
                            "url": article.get("url")
                        }
                    ))

                # Funding signals
                if any(w in content for w in ['funding', 'investment', 'raise',
                                               'financing', 'capital', 'loan']):
                    signals.append(FundingSignal(
                        signal_type="funding_activity",
                        signal_name="Funding Activity",
                        description="Company actively seeking or obtained funding",
                        strength="high",
                        score_boost=30,
                        source=self.get_name(),
                        metadata={
                            "article_title": article.get("title"),
                            "url": article.get("url")
                        }
                    ))

            # Deduplicate by signal type
            seen_types = set()
            unique_signals = []
            for s in signals:
                if s.signal_type not in seen_types:
                    seen_types.add(s.signal_type)
                    unique_signals.append(s)

            signals = unique_signals

            # Cache results
            self.cache.set(self.get_name(), cache_key,
                          [{"signal_type": s.signal_type, "signal_name": s.signal_name,
                            "description": s.description, "strength": s.strength,
                            "score_boost": s.score_boost, "source": s.source,
                            "metadata": s.metadata} for s in signals])

        except Exception as e:
            logger.error(f"News detection failed: {e}")

        return signals

    def _search_news(self, company_name: str) -> List[Dict[str, Any]]:
        """Search for news articles."""
        articles = []

        try:
            if self.api_key:
                # NewsAPI.org
                encoded_name = urllib.parse.quote(company_name)
                from_date = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')
                url = f"https://newsapi.org/v2/everything?q={encoded_name}&from={from_date}&sortBy=relevancy&apiKey={self.api_key}"

                response = self._make_request(url)
                articles = response.get("articles", [])[:10]

        except Exception as e:
            logger.error(f"News search failed: {e}")

        return articles


class SBALoanDetector(SignalDetector):
    """
    Detect SBA loan history signals.

    Companies with previous SBA loans are often good candidates
    for additional financing.

    Uses SBA.gov public data.
    """

    def get_name(self) -> str:
        return "sba_loans"

    def detect(self, company_name: str, state: Optional[str] = None,
               industry: Optional[str] = None, **kwargs) -> List[FundingSignal]:
        """Detect SBA loan history signals."""
        signals = []

        cache_key = f"sba:{company_name}:{state or ''}"
        cached = self.cache.get(self.get_name(), cache_key)
        if cached:
            return [FundingSignal(**s) for s in cached]

        try:
            loans = self._search_sba_loans(company_name, state)

            if loans:
                # Has previous SBA loans
                recent_loans = [l for l in loans
                              if self._is_recent_loan(l.get("approval_date"))]

                if recent_loans:
                    signals.append(FundingSignal(
                        signal_type="recent_sba_loan",
                        signal_name="Recent SBA Loan Recipient",
                        description="Received SBA loan in past 2 years - familiar with SBA process",
                        strength="medium",
                        score_boost=15,
                        source=self.get_name(),
                        metadata={
                            "loan_count": len(recent_loans),
                            "most_recent": recent_loans[0].get("approval_date")
                        }
                    ))
                else:
                    signals.append(FundingSignal(
                        signal_type="previous_sba_loan",
                        signal_name="Previous SBA Loan Recipient",
                        description="Has history of SBA financing - proven borrower",
                        strength="low",
                        score_boost=10,
                        source=self.get_name(),
                        metadata={"loan_count": len(loans)}
                    ))

            self.cache.set(self.get_name(), cache_key,
                          [{"signal_type": s.signal_type, "signal_name": s.signal_name,
                            "description": s.description, "strength": s.strength,
                            "score_boost": s.score_boost, "source": s.source,
                            "metadata": s.metadata} for s in signals])

        except Exception as e:
            logger.error(f"SBA detection failed: {e}")

        return signals

    def _is_recent_loan(self, date_str: Optional[str]) -> bool:
        """Check if loan is within past 2 years."""
        if not date_str:
            return False
        try:
            loan_date = datetime.fromisoformat(date_str)
            return (datetime.now() - loan_date).days <= 730
        except ValueError:
            return False

    def _search_sba_loans(self, company_name: str, state: Optional[str]) -> List[Dict[str, Any]]:
        """Search SBA loan database."""
        # SBA data available via data.sba.gov
        # Would need to download/query their datasets
        return []


class BusinessCreditDetector(SignalDetector):
    """
    Detect business credit signals.

    Credit indicators that suggest financing readiness:
    - Credit score trends
    - Payment history
    - Credit utilization
    - Trade references
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.api_key = self.api_key or os.environ.get('DNB_API_KEY')

    def get_name(self) -> str:
        return "business_credit"

    def detect(self, company_name: str, state: Optional[str] = None,
               industry: Optional[str] = None, **kwargs) -> List[FundingSignal]:
        """Detect credit-based funding signals."""
        signals = []

        # This would integrate with D&B, Experian Business, or Equifax Business
        # Placeholder for actual implementation

        return signals


class FundingSignalAnalyzer:
    """
    Main analyzer that combines multiple signal detectors.
    """

    def __init__(self, detectors: Optional[List[str]] = None,
                 api_keys: Optional[Dict[str, str]] = None,
                 cache: Optional[EnrichmentCache] = None,
                 max_workers: int = 3):
        """
        Initialize analyzer.

        Args:
            detectors: List of detector names to use
            api_keys: Dict of API keys by detector name
            cache: Shared cache instance
            max_workers: Max parallel detector calls
        """
        self.cache = cache or EnrichmentCache()
        self.max_workers = max_workers
        self.api_keys = api_keys or {}

        available_detectors = {
            "ucc_filings": UCCFilingDetector,
            "job_postings": JobPostingDetector,
            "news": NewsSignalDetector,
            "sba_loans": SBALoanDetector,
            "business_credit": BusinessCreditDetector
        }

        self.detectors: Dict[str, SignalDetector] = {}

        detectors_to_use = detectors or list(available_detectors.keys())
        for name in detectors_to_use:
            if name in available_detectors:
                api_key = self.api_keys.get(name)
                self.detectors[name] = available_detectors[name](
                    api_key=api_key,
                    cache=self.cache
                )

    def analyze(self, company_name: str, state: Optional[str] = None,
                industry: Optional[str] = None,
                detectors: Optional[List[str]] = None) -> FundingSignalReport:
        """
        Analyze a company for funding signals.

        Args:
            company_name: Company name
            state: State location
            industry: Industry category
            detectors: Specific detectors to use

        Returns:
            FundingSignalReport with all detected signals
        """
        report = FundingSignalReport(company_name=company_name)
        detectors_to_use = detectors or list(self.detectors.keys())

        # Run detectors in parallel
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {}
            for name in detectors_to_use:
                if name in self.detectors:
                    future = executor.submit(
                        self.detectors[name].detect,
                        company_name, state, industry
                    )
                    futures[future] = name

            for future in as_completed(futures):
                name = futures[future]
                report.sources_checked.append(name)
                try:
                    signals = future.result()
                    for signal in signals:
                        report.add_signal(signal)
                except Exception as e:
                    logger.error(f"Detector {name} failed: {e}")

        # Generate recommendations
        report.recommended_products = self._recommend_products(report)
        report.recommended_timing = self._recommend_timing(report)

        return report

    def _recommend_products(self, report: FundingSignalReport) -> List[str]:
        """Recommend financing products based on signals."""
        products = set()

        for signal in report.signals:
            if signal.signal_type in ["fleet_expansion", "equipment_news"]:
                products.add("Equipment Financing")
                products.add("Fleet Financing")
            elif signal.signal_type in ["expansion_news", "new_contract"]:
                products.add("Working Capital Line")
                products.add("Term Loan")
            elif signal.signal_type in ["ucc_expiring"]:
                products.add("Refinancing")
            elif signal.signal_type in ["hiring_surge", "leadership_expansion"]:
                products.add("Business Expansion Loan")

        if not products:
            products.add("General Business Loan")

        return list(products)

    def _recommend_timing(self, report: FundingSignalReport) -> str:
        """Recommend outreach timing based on signals."""
        high_urgency = any(s.signal_type in ["ucc_expiring", "funding_activity"]
                         for s in report.signals)
        growth_signals = any(s.signal_type in ["expansion_news", "hiring_surge", "fleet_expansion"]
                           for s in report.signals)

        if high_urgency:
            return "Immediate - Time-sensitive opportunity"
        elif growth_signals:
            return "Within 1-2 weeks - Active growth phase"
        elif report.signals:
            return "Within 30 days - Potential opportunity"
        else:
            return "Standard follow-up cadence"

    def analyze_batch(self, prospects: List[Dict[str, Any]],
                      name_field: str = "company_name",
                      state_field: str = "state",
                      industry_field: str = "industry",
                      progress_callback=None,
                      max_parallel: int = 5) -> List[Tuple[Dict[str, Any], FundingSignalReport]]:
        """
        Analyze a batch of prospects for funding signals.

        Args:
            prospects: List of prospect dictionaries
            name_field: Field name for company name
            state_field: Field name for state
            industry_field: Field name for industry
            progress_callback: Optional callback(current, total)
            max_parallel: Maximum parallel analyses

        Returns:
            List of tuples (original_prospect, FundingSignalReport)
        """
        results = []
        total = len(prospects)

        with ThreadPoolExecutor(max_workers=max_parallel) as executor:
            futures = {}

            for i, prospect in enumerate(prospects):
                future = executor.submit(
                    self.analyze,
                    company_name=prospect.get(name_field, ""),
                    state=prospect.get(state_field),
                    industry=prospect.get(industry_field)
                )
                futures[future] = (i, prospect)

            completed = 0
            for future in as_completed(futures):
                idx, prospect = futures[future]
                try:
                    report = future.result()
                    results.append((prospect, report))
                except Exception as e:
                    logger.error(f"Batch analysis failed for {prospect.get(name_field)}: {e}")
                    results.append((prospect, FundingSignalReport(prospect.get(name_field, ""))))

                completed += 1
                if progress_callback:
                    progress_callback(completed, total)

        # Sort by original order
        results.sort(key=lambda x: prospects.index(x[0]))
        return results


# Convenience function
def analyze_funding_signals(company_name: str, state: Optional[str] = None,
                           industry: Optional[str] = None) -> FundingSignalReport:
    """
    Quick funding signal analysis.

    Args:
        company_name: Company name
        state: State location
        industry: Industry category

    Returns:
        FundingSignalReport with detected signals
    """
    analyzer = FundingSignalAnalyzer()
    return analyzer.analyze(company_name, state, industry)
