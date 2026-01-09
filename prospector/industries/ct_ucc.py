"""
Connecticut UCC (Uniform Commercial Code) Lien Filings Prospector.

Uses Connecticut Open Data Portal (data.ct.gov) via Socrata API.
Dataset: Uniform Commercial Code (UCC) Lien Filings
API Endpoint: https://data.ct.gov/resource/xfev-8smz.json

UCC filings indicate businesses that have used secured financing - 
valuable for MCA prospecting as it shows prior borrowing activity.
"""

import os
import requests
from datetime import datetime
from typing import List, Optional, Callable
from prospector.core.base import IndustryProspector, ProspectRecord


class CTUCCProspector(IndustryProspector):
    """Prospector for Connecticut UCC Lien Filings."""
    
    BASE_URL = "https://data.ct.gov/resource/xfev-8smz.json"
    
    def __init__(self, app_token: Optional[str] = None):
        self.app_token = app_token or os.getenv("SOCRATA_APP_TOKEN")
        self.session = requests.Session()
        if self.app_token:
            self.session.headers['X-App-Token'] = self.app_token
    
    @property
    def industry_name(self) -> str:
        return "CT UCC Filings"
    
    @property
    def data_source(self) -> str:
        return "Connecticut Open Data (data.ct.gov)"
    
    def get_industry_name(self) -> str:
        return self.industry_name
    
    def fetch_prospects(self):
        return []
    
    def parse_record(self, raw_record):
        return self._parse_record(raw_record)
    
    def search(
        self,
        debtor_name: Optional[str] = None,
        secured_party: Optional[str] = None,
        cities: Optional[List[str]] = None,
        lien_types: Optional[List[str]] = None,
        filed_after: Optional[str] = None,
        filed_before: Optional[str] = None,
        active_only: bool = True,
        limit: int = 1000,
        progress_callback: Optional[Callable[[int, str], None]] = None,
    ) -> List[ProspectRecord]:
        """
        Search Connecticut UCC lien filings.
        
        Args:
            debtor_name: Search by debtor (business) name (partial match)
            secured_party: Search by secured party (lender) name
            cities: Filter by debtor city
            lien_types: Filter by lien type (e.g., 'UCC', 'Federal Tax Lien')
            filed_after: Only filings after this date (YYYY-MM-DD)
            filed_before: Only filings before this date (YYYY-MM-DD)
            active_only: Only return active/unlapsed liens
            limit: Maximum records to return
            progress_callback: Function for progress updates
        """
        if progress_callback:
            progress_callback(5, "Building query for CT UCC filings...")
        
        where_clauses = []
        
        if debtor_name:
            where_clauses.append(f"upper(debtor_name) like '%{debtor_name.upper()}%'")
        
        if secured_party:
            where_clauses.append(f"upper(secured_party_name) like '%{secured_party.upper()}%'")
        
        if cities:
            city_conditions = " OR ".join([f"upper(debtor_city)='{c.upper()}'" for c in cities])
            where_clauses.append(f"({city_conditions})")
        
        if lien_types:
            type_conditions = " OR ".join([f"lien_type='{t}'" for t in lien_types])
            where_clauses.append(f"({type_conditions})")
        
        if filed_after:
            where_clauses.append(f"file_date >= '{filed_after}'")
        
        if filed_before:
            where_clauses.append(f"file_date <= '{filed_before}'")
        
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
                "$order": "file_date DESC",
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
                    progress_callback(progress_pct, f"Fetched {len(all_records):,} UCC filings...")
                
                if len(records) < batch_size:
                    break
                    
            except requests.RequestException as e:
                if progress_callback:
                    progress_callback(0, f"API error: {str(e)}")
                raise
        
        if progress_callback:
            progress_callback(75, f"Processing {len(all_records):,} UCC filings...")
        
        prospects = []
        for record in all_records:
            prospect = self._parse_record(record)
            if prospect:
                prospects.append(prospect)
        
        if progress_callback:
            progress_callback(90, "Scoring prospects...")
        
        for prospect in prospects:
            prospect.score = self._calculate_score(prospect, record)
        
        prospects.sort(key=lambda x: x.score, reverse=True)
        
        if progress_callback:
            progress_callback(100, f"Found {len(prospects):,} UCC filings")
        
        return prospects
    
    def _parse_record(self, record: dict) -> Optional[ProspectRecord]:
        """Parse a raw Socrata record into a ProspectRecord."""
        debtor_name = record.get("debtor_name", "").strip()
        if not debtor_name:
            return None
        
        address_parts = []
        if record.get("debtor_address"):
            address_parts.append(record.get("debtor_address"))
        
        city = record.get("debtor_city", "")
        state = record.get("debtor_state", "CT")
        zip_code = record.get("debtor_zip", "")
        
        if city or state or zip_code:
            address_parts.append(f"{city}, {state} {zip_code}".strip())
        
        file_date = record.get("file_date", "")
        if file_date:
            try:
                file_date = file_date[:10]
            except:
                pass
        
        lapse_date = record.get("lapse_date", "")
        if lapse_date:
            try:
                lapse_date = lapse_date[:10]
            except:
                pass
        
        return ProspectRecord(
            company_name=debtor_name,
            address=", ".join(address_parts) if address_parts else "",
            city=city,
            state=state,
            zip_code=zip_code,
            phone="",
            email="",
            website="",
            industry="UCC Lien Filing",
            employee_count=0,
            annual_revenue=0,
            years_in_business=0,
            score=0,
            source="CT UCC Filings",
            source_id=record.get("file_number", ""),
            raw_data={
                "file_number": record.get("file_number", ""),
                "lien_type": record.get("lien_type", ""),
                "secured_party": record.get("secured_party_name", ""),
                "file_date": file_date,
                "lapse_date": lapse_date,
                "status": record.get("status", ""),
                "collateral": record.get("collateral_description", ""),
            }
        )
    
    def _calculate_score(self, prospect: ProspectRecord, record: dict) -> int:
        """Calculate a score for UCC-based prospects."""
        score = 50
        
        lien_type = record.get("lien_type", "")
        if lien_type == "UCC":
            score += 15
        elif "Equipment" in lien_type or "Lease" in lien_type:
            score += 20
        
        file_date = record.get("file_date", "")
        if file_date:
            try:
                filed = datetime.strptime(file_date[:10], "%Y-%m-%d")
                days_ago = (datetime.now() - filed).days
                if days_ago <= 180:
                    score += 20
                elif days_ago <= 365:
                    score += 10
                elif days_ago <= 730:
                    score += 5
            except:
                pass
        
        if prospect.city:
            score += 5
        
        if prospect.zip_code:
            score += 5
        
        collateral = record.get("collateral_description", "").lower()
        high_value_keywords = ["equipment", "vehicle", "inventory", "accounts receivable", "machinery"]
        for keyword in high_value_keywords:
            if keyword in collateral:
                score += 5
                break
        
        return min(100, score)
    
    def get_lien_types(self) -> List[str]:
        """Get available lien types from the dataset."""
        params = {
            "$select": "lien_type",
            "$group": "lien_type",
            "$limit": 100,
        }
        
        try:
            response = self.session.get(self.BASE_URL, params=params, timeout=30)
            response.raise_for_status()
            results = response.json()
            return sorted([r.get("lien_type", "") for r in results if r.get("lien_type")])
        except:
            return ["UCC", "Federal Tax Lien", "State Tax Lien", "Judgment Lien"]
