"""
Washington State Contractors Prospector

Pulls licensed contractors from Washington's open data portal via Socrata API.
Dataset: https://data.wa.gov/Labor/Contractor-Load/g526-rd4x

Includes business name, primary principal name, address, city, state, zip, and phone number.
"""

import requests
from typing import List, Optional, Callable
from prospector.core.base import IndustryProspector, ProspectRecord


class WAContractorProspector(IndustryProspector):
    """Prospector for Washington State licensed contractors."""
    
    BASE_URL = "https://data.wa.gov/resource/g526-rd4x.json"
    
    def __init__(self, app_token: Optional[str] = None):
        self.app_token = app_token
        self.session = requests.Session()
        if app_token:
            self.session.headers['X-App-Token'] = app_token
    
    @property
    def industry_name(self) -> str:
        return "WA Contractors"
    
    @property
    def data_source(self) -> str:
        return "Washington State Open Data (data.wa.gov)"
    
    def search(
        self,
        cities: Optional[List[str]] = None,
        counties: Optional[List[str]] = None,
        business_name: Optional[str] = None,
        active_only: bool = True,
        limit: int = 1000,
        progress_callback: Optional[Callable[[int, str], None]] = None,
    ) -> List[ProspectRecord]:
        """
        Search Washington State licensed contractors.
        
        Args:
            cities: Filter by city names
            counties: Filter by county names
            business_name: Search by business name (partial match)
            active_only: Only return active licenses
            limit: Maximum records to return
            progress_callback: Function for progress updates
        """
        if progress_callback:
            progress_callback(5, "Building query for WA contractors...")
        
        where_clauses = []
        
        if active_only:
            where_clauses.append("status='Active'")
        
        if cities:
            city_conditions = " OR ".join([f"upper(city)='{c.upper()}'" for c in cities])
            where_clauses.append(f"({city_conditions})")
        
        if counties:
            county_conditions = " OR ".join([f"upper(county)='{c.upper()}'" for c in counties])
            where_clauses.append(f"({county_conditions})")
        
        if business_name:
            where_clauses.append(f"upper(businessname) like '%{business_name.upper()}%'")
        
        where_clause = " AND ".join(where_clauses) if where_clauses else None
        
        if progress_callback:
            progress_callback(10, "Fetching records from WA data portal...")
        
        all_records = []
        offset = 0
        batch_size = 1000
        
        while len(all_records) < limit:
            params = {
                "$limit": min(batch_size, limit - len(all_records)),
                "$offset": offset,
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
                record.get('businessname', '').upper().strip(),
                record.get('ubi', ''),
            )
            if key in seen or not key[0]:
                continue
            seen.add(key)
            
            prospect = self._parse_record(record)
            if prospect:
                prospects.append(prospect)
        
        if progress_callback:
            progress_callback(85, f"Scoring {len(prospects):,} prospects...")
        
        for i, prospect in enumerate(prospects):
            prospect.score = self._calculate_score(prospect, all_records[i] if i < len(all_records) else {})
        
        prospects.sort(key=lambda x: x.score, reverse=True)
        
        if progress_callback:
            progress_callback(100, f"Found {len(prospects):,} WA contractors")
        
        return prospects[:limit]
    
    def _parse_record(self, record: dict) -> Optional[ProspectRecord]:
        """Parse a WA contractor record into a ProspectRecord."""
        name = record.get('businessname', '').strip()
        if not name:
            return None
        
        address_parts = []
        if record.get('address1'):
            address_parts.append(record['address1'])
        if record.get('address2'):
            address_parts.append(record['address2'])
        
        city = record.get('city', '')
        state = record.get('state', 'WA')
        zip_code = record.get('zip', '')
        
        phone = record.get('phonenumber', '')
        if phone:
            phone = ''.join(filter(str.isdigit, str(phone)))
            if len(phone) == 10:
                phone = f"({phone[:3]}) {phone[3:6]}-{phone[6:]}"
            elif len(phone) == 11 and phone.startswith('1'):
                phone = f"({phone[1:4]}) {phone[4:7]}-{phone[7:]}"
        
        return ProspectRecord(
            company_name=name,
            address=', '.join(address_parts) if address_parts else None,
            city=city,
            state=state,
            zip_code=zip_code[:5] if zip_code else None,
            phone=phone if phone else None,
            email=None,
            contact_name=record.get('primaryprincipalname', ''),
            industry="Contractor",
            sub_industry=record.get('specialty', ''),
            employee_count=None,
            revenue=None,
            years_in_business=None,
            score=0,
            source=self.data_source,
            source_id=record.get('ubi', ''),
            raw_data={
                'ubi': record.get('ubi', ''),
                'license_number': record.get('contractorlicensenumber', ''),
                'county': record.get('county', ''),
                'principal_name': record.get('primaryprincipalname', ''),
                'specialty': record.get('specialty', ''),
            },
        )
    
    def _calculate_score(self, prospect: ProspectRecord, record: dict) -> int:
        """Calculate MCA prospect score."""
        score = 50
        
        if prospect.phone:
            score += 20
        
        if prospect.contact_name:
            score += 10
        
        if prospect.address:
            score += 10
        
        if prospect.city:
            score += 5
        
        specialty = record.get('specialty', '').upper() if record else ''
        high_value_specialties = ['GENERAL', 'ELECTRICAL', 'PLUMBING', 'HVAC', 'ROOFING']
        for spec in high_value_specialties:
            if spec in specialty:
                score += 5
                break
        
        return min(100, max(0, score))
