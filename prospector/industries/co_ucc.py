"""
Colorado UCC (Uniform Commercial Code) Lien Filings Prospector.

Uses Colorado Information Marketplace (data.colorado.gov) via Socrata API.
Datasets:
- Filing Info: https://data.colorado.gov/resource/wffy-3uut.json
- Debtor Info: https://data.colorado.gov/resource/8upq-58vz.json

UCC filings indicate businesses that have used secured financing - 
valuable for MCA prospecting as it shows prior borrowing activity.
"""

import os
import requests
from datetime import datetime
from typing import List, Optional, Callable
from prospector.core.base import IndustryProspector, ProspectRecord


class COUCCProspector(IndustryProspector):
    """Prospector for Colorado UCC Lien Filings."""
    
    FILING_URL = "https://data.colorado.gov/resource/wffy-3uut.json"
    DEBTOR_URL = "https://data.colorado.gov/resource/8upq-58vz.json"
    
    def __init__(self, app_token: Optional[str] = None):
        self.app_token = app_token or os.getenv("SOCRATA_APP_TOKEN")
        self.session = requests.Session()
        if self.app_token:
            self.session.headers['X-App-Token'] = self.app_token
    
    @property
    def industry_name(self) -> str:
        return "CO UCC Filings"
    
    @property
    def data_source(self) -> str:
        return "Colorado Information Marketplace (data.colorado.gov)"
    
    def get_industry_name(self) -> str:
        return self.industry_name
    
    def fetch_prospects(self):
        return []
    
    def parse_record(self, raw_record):
        return self._parse_record(raw_record)
    
    def search(
        self,
        debtor_name: Optional[str] = None,
        filing_type: Optional[str] = None,
        filed_after: Optional[str] = None,
        filed_before: Optional[str] = None,
        limit: int = 1000,
        offset: int = 0,
        progress_callback: Optional[Callable[[int, str], None]] = None,
    ) -> List[ProspectRecord]:
        """
        Search Colorado UCC lien filings.
        
        Args:
            debtor_name: Search by debtor (business) name (partial match)
            filing_type: Filter by filing type (e.g., 'UCC1', 'UCC3')
            filed_after: Only filings after this date (YYYY-MM-DD)
            filed_before: Only filings before this date (YYYY-MM-DD)
            limit: Maximum records to return
            offset: Number of records to skip (for pagination)
            progress_callback: Function for progress updates
        """
        if progress_callback:
            if offset > 0:
                progress_callback(5, f"Fetching CO UCC filings starting from {offset:,}...")
            else:
                progress_callback(5, "Building query for CO UCC filings...")
        
        where_clauses = []
        
        if filing_type:
            where_clauses.append(f"filingtype='{filing_type}'")
        
        if filed_after:
            where_clauses.append(f"filingdate >= '{filed_after}T00:00:00.000'")
        
        if filed_before:
            where_clauses.append(f"filingdate <= '{filed_before}T23:59:59.000'")
        
        where_clause = " AND ".join(where_clauses) if where_clauses else None
        
        if progress_callback:
            progress_callback(10, "Fetching records from CO data portal...")
        
        all_records = []
        current_offset = offset
        batch_size = 1000
        
        while len(all_records) < limit:
            params = {
                "$limit": min(batch_size, limit - len(all_records)),
                "$offset": current_offset,
                "$order": "filingdate DESC",
            }
            
            if where_clause:
                params["$where"] = where_clause
            
            try:
                response = self.session.get(self.FILING_URL, params=params, timeout=60)
                response.raise_for_status()
                records = response.json()
                
                if not records:
                    break
                
                all_records.extend(records)
                current_offset += len(records)
                
                progress_pct = min(50, 10 + int(40 * len(all_records) / limit))
                if progress_callback:
                    progress_callback(progress_pct, f"Fetched {len(all_records):,} CO filing records...")
                
                if len(records) < batch_size:
                    break
                    
            except requests.RequestException as e:
                if progress_callback:
                    progress_callback(0, f"API error: {str(e)}")
                raise
        
        if progress_callback:
            progress_callback(55, f"Enriching with debtor information...")
        
        file_ids = list(set(r.get("fileid") for r in all_records if r.get("fileid")))
        debtor_map = {}
        
        if debtor_name:
            debtor_where = f"upper(organizationname) like '%{debtor_name.upper()}%'"
            try:
                debtor_params = {
                    "$limit": 5000,
                    "$where": debtor_where,
                }
                response = self.session.get(self.DEBTOR_URL, params=debtor_params, timeout=60)
                response.raise_for_status()
                debtor_records = response.json()
                for dr in debtor_records:
                    fid = dr.get("fileid")
                    if fid:
                        debtor_map[fid] = dr
            except:
                pass
        elif file_ids[:500]:
            for batch_start in range(0, min(len(file_ids), 500), 100):
                batch_ids = file_ids[batch_start:batch_start+100]
                id_conditions = " OR ".join([f"fileid='{fid}'" for fid in batch_ids])
                try:
                    debtor_params = {
                        "$limit": 1000,
                        "$where": f"({id_conditions})",
                    }
                    response = self.session.get(self.DEBTOR_URL, params=debtor_params, timeout=60)
                    response.raise_for_status()
                    debtor_records = response.json()
                    for dr in debtor_records:
                        fid = dr.get("fileid")
                        if fid:
                            debtor_map[fid] = dr
                except:
                    pass
        
        if progress_callback:
            progress_callback(75, f"Processing {len(all_records):,} CO UCC filings...")
        
        prospects = []
        for record in all_records:
            file_id = record.get("fileid")
            debtor_info = debtor_map.get(file_id, {})
            prospect = self._parse_record(record, debtor_info)
            if prospect:
                if debtor_name:
                    if debtor_name.upper() in prospect.company_name.upper():
                        prospects.append(prospect)
                else:
                    prospects.append(prospect)
        
        if progress_callback:
            progress_callback(90, "Scoring prospects...")
        
        for prospect in prospects:
            prospect.prospect_score = self._calculate_score(prospect)
        
        prospects.sort(key=lambda x: x.prospect_score, reverse=True)
        
        if progress_callback:
            progress_callback(100, f"Found {len(prospects):,} CO UCC filings")
        
        return prospects[:limit]
    
    def _parse_record(self, filing: dict, debtor: dict = None) -> Optional[ProspectRecord]:
        """Parse filing and debtor records into a ProspectRecord."""
        debtor = debtor or {}
        
        debtor_name = debtor.get("organizationname", "").strip()
        if not debtor_name:
            debtor_name = f"Filing #{filing.get('transactionid', filing.get('masterdocumentid', 'Unknown'))}"
        
        address = debtor.get("address1", "")
        city = debtor.get("city", "")
        state = debtor.get("state", "CO")
        zip_code = debtor.get("zipcode", "")
        
        file_date = filing.get("filingdate", "")
        if file_date:
            try:
                file_date = file_date[:10]
            except:
                pass
        
        doc_type = filing.get("documenttype", "")
        filing_type = filing.get("filingtype", "")
        
        return ProspectRecord(
            company_name=debtor_name,
            address=address,
            city=city,
            state=state,
            zip_code=zip_code,
            industry_id=filing.get("transactionid", filing.get("masterdocumentid", "")),
            source="CO UCC Filings",
            industry_data={
                "Transaction ID": filing.get("transactionid", ""),
                "Master Doc ID": filing.get("masterdocumentid", ""),
                "Filing Type": filing_type,
                "Document Type": doc_type,
                "Transaction Type": filing.get("transactiontype", ""),
                "Filing Date": file_date,
                "Continuation": "Yes" if filing.get("continuation") else "No",
                "Terminated": "Yes" if filing.get("terminationflag") else "No",
            }
        )
    
    def _calculate_score(self, prospect: ProspectRecord) -> int:
        """Calculate a score for UCC-based prospects."""
        score = 50
        
        data = prospect.industry_data
        filing_type = data.get("Filing Type", "")
        if filing_type == "ucc":
            score += 15
        elif filing_type == "efs":
            score += 12
        
        trans_type = data.get("Transaction Type", "")
        if trans_type == "Initial":
            score += 10
        elif trans_type == "Amendment":
            score += 5
        
        file_date = data.get("Filing Date", "")
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
        
        return min(100, score)
    
    def get_filing_types(self) -> List[str]:
        """Get available filing types from the dataset."""
        params = {
            "$select": "filingtype",
            "$group": "filingtype",
            "$limit": 50,
        }
        
        try:
            response = self.session.get(self.FILING_URL, params=params, timeout=30)
            response.raise_for_status()
            results = response.json()
            return sorted([r.get("filingtype", "") for r in results if r.get("filingtype")])
        except:
            return ["ucc", "efs", "lien_hosp", "lien_irs"]
