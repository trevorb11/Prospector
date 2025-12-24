"""
Connecticut Licensed Businesses Prospector

Pulls licensed businesses from Connecticut's open data portal via Socrata API.
Dataset: https://data.ct.gov/Business/All-Licenses-and-Credentials/ngch-56tr

Includes contractors, CPAs, real estate agents, restaurants, and many other
licensed business types - great for MCA leads and referral partner discovery.
"""

import requests
from typing import List, Optional, Callable
from datetime import datetime
from prospector.core.base import IndustryProspector, ProspectRecord


class CTLicenseProspector(IndustryProspector):
    """Prospector for Connecticut licensed businesses."""
    
    BASE_URL = "https://data.ct.gov/resource/ngch-56tr.json"
    
    BUSINESS_TYPES = [
        "BUSINESS",
        "LIMITED LIABILITY COMPANY", 
        "CORPORATION",
        "SOLE PROPRIETOR",
        "PARTNERSHIP",
        "COMPANY",
        "NON-PROFIT CORPORATION",
        "LIMITED LIABILITY COMPANY (SINGLE MEMBER)",
        "LIMITED LIABILITY PARTNERSHIP",
    ]
    
    MCA_RELEVANT_CREDENTIALS = [
        "HOME IMPROVEMENT CONTRACTOR",
        "HOME IMPROVEMENT SALESPERSON",
        "REAL ESTATE BROKER",
        "REAL ESTATE SALESPERSON",
        "CERTIFIED PUBLIC ACCOUNTANT CERTIFICATE",
        "PROFESSIONAL ENGINEER",
        "ELECTRICAL UNLIMITED JOURNEYPERSON",
        "HEATING, PIPING & COOLING LIMITED JOURNEYPERSON",
        "PLUMBING UNLIMITED JOURNEYPERSON",
        "BAKERY",
        "RESTAURANT",
        "CATERER",
        "FOOD SERVICE ESTABLISHMENT",
        "AUTO DEALER",
        "AUTO BODY REPAIRER",
        "AUTO GLASS INSTALLER",
        "GENERAL CONTRACTOR",
    ]
    
    REFERRAL_PARTNER_CREDENTIALS = [
        "CERTIFIED PUBLIC ACCOUNTANT CERTIFICATE",
        "Attorney",
        "INSURANCE PRODUCER",
        "REAL ESTATE BROKER",
        "INVESTMENT ADVISER",
        "Securities - Broker-Dealer",
    ]
    
    def __init__(self, app_token: Optional[str] = None):
        self.app_token = app_token
        self.session = requests.Session()
        if app_token:
            self.session.headers['X-App-Token'] = app_token
    
    @property
    def industry_name(self) -> str:
        return "CT Licensed Businesses"
    
    @property
    def data_source(self) -> str:
        return "Connecticut Open Data Portal (data.ct.gov)"
    
    def search(
        self,
        credential_types: Optional[List[str]] = None,
        entity_types: Optional[List[str]] = None,
        cities: Optional[List[str]] = None,
        active_only: bool = True,
        businesses_only: bool = True,
        limit: int = 1000,
        progress_callback: Optional[Callable[[int, str], None]] = None,
    ) -> List[ProspectRecord]:
        """
        Search Connecticut licensed businesses.
        
        Args:
            credential_types: Filter by license types (e.g., "HOME IMPROVEMENT CONTRACTOR")
            entity_types: Filter by entity types (e.g., "CORPORATION", "LLC")
            cities: Filter by city names
            active_only: Only return active licenses
            businesses_only: Exclude individual licenses (focus on businesses)
            limit: Maximum records to return
            progress_callback: Function for progress updates
        """
        if progress_callback:
            progress_callback(5, "Building query for CT licensed businesses...")
        
        where_clauses = []
        
        if active_only:
            where_clauses.append("status='ACTIVE'")
        
        if businesses_only:
            type_conditions = " OR ".join([f"type='{t}'" for t in self.BUSINESS_TYPES])
            where_clauses.append(f"({type_conditions})")
        
        if credential_types:
            cred_conditions = " OR ".join([f"credential='{c}'" for c in credential_types])
            where_clauses.append(f"({cred_conditions})")
        
        if cities:
            city_conditions = " OR ".join([f"upper(city)='{c.upper()}'" for c in cities])
            where_clauses.append(f"({city_conditions})")
        
        where_clause = " AND ".join(where_clauses) if where_clauses else None
        
        if progress_callback:
            progress_callback(10, "Fetching records from CT data portal...")
        
        all_records = []
        offset = 0
        batch_size = 1000
        
        while len(all_records) < limit:
            params = {
                "$limit": min(batch_size, limit - len(all_records)),
                "$offset": offset,
                "$order": "recordrefreshedon DESC",
            }
            
            if where_clause:
                params["$where"] = where_clause
            
            try:
                response = self.session.get(self.BASE_URL, params=params, timeout=60)
                response.raise_for_status()
                records = response.json()
                
                if not records:
                    break
                
                all_records.extend(records)
                offset += len(records)
                
                progress_pct = min(70, 10 + int(60 * len(all_records) / limit))
                if progress_callback:
                    progress_callback(progress_pct, f"Fetched {len(all_records):,} records...")
                
                if len(records) < batch_size:
                    break
                    
            except requests.RequestException as e:
                if progress_callback:
                    progress_callback(0, f"API error: {str(e)}")
                raise
        
        if progress_callback:
            progress_callback(75, f"Processing {len(all_records):,} records...")
        
        seen = set()
        prospects = []
        
        for record in all_records:
            key = (
                record.get('name', '').upper().strip(),
                record.get('credential', ''),
                record.get('credentialnumber', ''),
            )
            if key in seen:
                continue
            seen.add(key)
            
            prospect = self._parse_record(record)
            if prospect:
                prospects.append(prospect)
        
        if progress_callback:
            progress_callback(85, f"Scoring {len(prospects):,} prospects...")
        
        for prospect in prospects:
            prospect.score = self._calculate_score(prospect, record)
        
        prospects.sort(key=lambda x: x.score, reverse=True)
        
        if progress_callback:
            progress_callback(100, f"Found {len(prospects):,} CT licensed businesses")
        
        return prospects[:limit]
    
    def search_referral_partners(
        self,
        cities: Optional[List[str]] = None,
        limit: int = 500,
        progress_callback: Optional[Callable[[int, str], None]] = None,
    ) -> List[ProspectRecord]:
        """
        Search for potential referral partners (CPAs, attorneys, insurance agents).
        """
        return self.search(
            credential_types=self.REFERRAL_PARTNER_CREDENTIALS,
            cities=cities,
            active_only=True,
            businesses_only=False,
            limit=limit,
            progress_callback=progress_callback,
        )
    
    def search_contractors(
        self,
        cities: Optional[List[str]] = None,
        limit: int = 1000,
        progress_callback: Optional[Callable[[int, str], None]] = None,
    ) -> List[ProspectRecord]:
        """
        Search specifically for contractors (home improvement, electrical, plumbing, etc.)
        """
        contractor_types = [
            "HOME IMPROVEMENT CONTRACTOR",
            "ELECTRICAL UNLIMITED JOURNEYPERSON",
            "HEATING, PIPING & COOLING LIMITED JOURNEYPERSON",
            "PLUMBING UNLIMITED JOURNEYPERSON",
            "GENERAL CONTRACTOR",
        ]
        return self.search(
            credential_types=contractor_types,
            cities=cities,
            active_only=True,
            businesses_only=True,
            limit=limit,
            progress_callback=progress_callback,
        )
    
    def _parse_record(self, record: dict) -> Optional[ProspectRecord]:
        """Parse a CT license record into a ProspectRecord."""
        name = record.get('name', '').strip()
        if not name:
            return None
        
        address_parts = []
        if record.get('address'):
            address_parts.append(record['address'])
        
        city = record.get('city', '')
        state = record.get('state', 'CT')
        zip_code = record.get('zip', '')
        
        if city:
            address_parts.append(f"{city}, {state} {zip_code}".strip())
        
        expiration = record.get('expirationdate', '')
        if expiration:
            try:
                exp_date = datetime.fromisoformat(expiration.replace('Z', '+00:00'))
                expiration = exp_date.strftime('%Y-%m-%d')
            except:
                pass
        
        return ProspectRecord(
            company_name=name,
            address=', '.join(address_parts) if address_parts else None,
            city=city,
            state=state,
            zip_code=zip_code[:5] if zip_code else None,
            phone=None,
            email=None,
            contact_name=name if record.get('type') == 'INDIVIDUAL' else None,
            industry=record.get('credential', 'Licensed Business'),
            sub_industry=record.get('type', ''),
            employee_count=None,
            revenue=None,
            years_in_business=None,
            score=0,
            source=self.data_source,
            source_id=record.get('credentialid', ''),
            raw_data={
                'credential_type': record.get('credentialtype', ''),
                'credential_number': record.get('credentialnumber', ''),
                'full_credential_code': record.get('fullcredentialcode', ''),
                'status': record.get('status', ''),
                'status_reason': record.get('statusreason', ''),
                'issue_date': record.get('issuedate', ''),
                'expiration_date': expiration,
                'entity_type': record.get('type', ''),
            },
        )
    
    def _calculate_score(self, prospect: ProspectRecord, record: dict) -> int:
        """Calculate MCA prospect score."""
        score = 50
        
        entity_type = record.get('type', '')
        if entity_type in ['CORPORATION', 'LIMITED LIABILITY COMPANY']:
            score += 15
        elif entity_type in ['BUSINESS', 'PARTNERSHIP']:
            score += 10
        elif entity_type == 'SOLE PROPRIETOR':
            score += 5
        elif entity_type == 'INDIVIDUAL':
            score -= 10
        
        credential = record.get('credential', '')
        high_value_credentials = [
            'HOME IMPROVEMENT CONTRACTOR',
            'GENERAL CONTRACTOR',
            'RESTAURANT',
            'AUTO DEALER',
            'REAL ESTATE BROKER',
        ]
        if credential in high_value_credentials:
            score += 15
        elif credential in self.MCA_RELEVANT_CREDENTIALS:
            score += 10
        
        if record.get('status') == 'ACTIVE':
            score += 10
        
        expiration = record.get('expirationdate', '')
        if expiration:
            try:
                exp_date = datetime.fromisoformat(expiration.replace('Z', '+00:00'))
                if exp_date > datetime.now(exp_date.tzinfo):
                    years_left = (exp_date - datetime.now(exp_date.tzinfo)).days / 365
                    if years_left > 1:
                        score += 5
            except:
                pass
        
        if prospect.address:
            score += 5
        
        return min(100, max(0, score))


def get_credential_types() -> List[str]:
    """Get list of available credential types for filtering."""
    url = "https://data.ct.gov/resource/ngch-56tr.json"
    params = {
        "$select": "credential,count(*)",
        "$group": "credential",
        "$order": "count(*) DESC",
        "$limit": 100,
    }
    try:
        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()
        return [r['credential'] for r in response.json() if r.get('credential')]
    except:
        return []
