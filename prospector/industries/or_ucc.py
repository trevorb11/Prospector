"""
Oregon UCC (Uniform Commercial Code) Lien Filings Prospector.

Uses Oregon Open Data Portal (data.oregon.gov) via Socrata API.
Dataset: UCC List of Filings
API Endpoint: https://data.oregon.gov/resource/se62-vm8c.json

UCC filings indicate businesses that have used secured financing - 
valuable for MCA prospecting as it shows prior borrowing activity.
"""

import os
import requests
from datetime import datetime
from typing import List, Optional, Callable
from prospector.core.base import IndustryProspector, ProspectRecord


class ORUCCProspector(IndustryProspector):
    """Prospector for Oregon UCC Lien Filings."""
    
    BASE_URL = "https://data.oregon.gov/resource/se62-vm8c.json"
    
    def __init__(self, app_token: Optional[str] = None):
        self.app_token = app_token or os.getenv("SOCRATA_APP_TOKEN")
        self.session = requests.Session()
        if self.app_token:
            self.session.headers['X-App-Token'] = self.app_token
    
    @property
    def industry_name(self) -> str:
        return "OR UCC Filings"
    
    @property
    def data_source(self) -> str:
        return "Oregon Open Data (data.oregon.gov)"
    
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
        lien_types: Optional[List[str]] = None,
        filed_after: Optional[str] = None,
        filed_before: Optional[str] = None,
        limit: int = 1000,
        offset: int = 0,
        progress_callback: Optional[Callable[[int, str], None]] = None,
    ) -> List[ProspectRecord]:
        """
        Search Oregon UCC lien filings.
        
        Args:
            debtor_name: Search by debtor (business) name (partial match)
            secured_party: Search by secured party (lender) name
            lien_types: Filter by lien type (e.g., 'UCC')
            filed_after: Only filings after this date (YYYY-MM-DD)
            filed_before: Only filings before this date (YYYY-MM-DD)
            limit: Maximum records to return
            offset: Number of records to skip (for pagination)
            progress_callback: Function for progress updates
        """
        if progress_callback:
            if offset > 0:
                progress_callback(5, f"Fetching OR UCC filings starting from {offset:,}...")
            else:
                progress_callback(5, "Building query for OR UCC filings...")
        
        where_clauses = []
        
        if debtor_name:
            where_clauses.append(f"upper(debtor_name) like '%{debtor_name.upper()}%'")
        
        if secured_party:
            where_clauses.append(f"upper(secured_party) like '%{secured_party.upper()}%'")
        
        if lien_types:
            type_conditions = " OR ".join([f"lien_type='{t}'" for t in lien_types])
            where_clauses.append(f"({type_conditions})")
        
        if filed_after:
            where_clauses.append(f"filing_date >= '{filed_after}'")
        
        if filed_before:
            where_clauses.append(f"filing_date <= '{filed_before}'")
        
        where_clause = " AND ".join(where_clauses) if where_clauses else None
        
        if progress_callback:
            progress_callback(10, "Fetching records from OR data portal...")
        
        all_records = []
        current_offset = offset
        batch_size = 1000
        
        while len(all_records) < limit:
            params = {
                "$limit": min(batch_size, limit - len(all_records)),
                "$offset": current_offset,
                "$order": "filing_date DESC",
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
                current_offset += len(records)
                
                progress_pct = min(70, 10 + int(60 * len(all_records) / limit))
                if progress_callback:
                    progress_callback(progress_pct, f"Fetched {len(all_records):,} OR UCC filings...")
                
                if len(records) < batch_size:
                    break
                    
            except requests.RequestException as e:
                if progress_callback:
                    progress_callback(0, f"API error: {str(e)}")
                raise
        
        if progress_callback:
            progress_callback(75, f"Processing {len(all_records):,} OR UCC filings...")
        
        prospects = []
        for record in all_records:
            prospect = self._parse_record(record)
            if prospect:
                prospects.append(prospect)
        
        if progress_callback:
            progress_callback(90, "Scoring prospects...")
        
        for i, prospect in enumerate(prospects):
            prospect.prospect_score = self._calculate_score(prospect, all_records[i] if i < len(all_records) else {})
        
        prospects.sort(key=lambda x: x.prospect_score, reverse=True)
        
        if progress_callback:
            progress_callback(100, f"Found {len(prospects):,} OR UCC filings")
        
        return prospects
    
    def _parse_record(self, record: dict) -> Optional[ProspectRecord]:
        """Parse a raw Socrata record into a ProspectRecord."""
        debtor_name = record.get("debtor_name", "").strip()
        if not debtor_name:
            return None
        
        file_date = record.get("filing_date", "")
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
            state="OR",
            industry_id=record.get("file_number", record.get("lien_number", "")),
            source="OR UCC Filings",
            industry_data={
                "File Number": record.get("file_number", ""),
                "Lien Number": record.get("lien_number", ""),
                "Lien Type": record.get("lien_type", ""),
                "File Type": record.get("file_type", ""),
                "Secured Party": record.get("secured_party", ""),
                "Filing Date": file_date,
                "Lapse Date": lapse_date,
            }
        )
    
    def _calculate_score(self, prospect: ProspectRecord, record: dict) -> int:
        """Calculate a score for UCC-based prospects."""
        score = 50
        
        lien_type = record.get("lien_type", "")
        if lien_type == "UCC":
            score += 15
        
        file_date = record.get("filing_date", "")
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
        
        return min(100, score)
