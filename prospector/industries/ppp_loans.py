"""
PPP Loan Recipients Industry Prospector

Fetches business data from SBA PPP loan program public data.
These businesses received Paycheck Protection Program loans during COVID-19.

Data source: https://data.sba.gov/dataset/ppp-foia
"""

import os
import io
import requests
import pandas as pd
from typing import List, Optional, Dict, Any, Callable
from pathlib import Path

from ..core.base import ProspectRecord, IndustryProspector


class PPPLoanProspector(IndustryProspector):
    """Prospector for SBA PPP loan recipients."""
    
    INDUSTRY_NAME = "ppp_loans"
    DISPLAY_NAME = "PPP Loan Recipients"
    
    # PPP data file URLs from data.sba.gov
    DATA_URL_150K_PLUS = "https://data.sba.gov/dataset/8aa276e2-6cab-4f86-aca4-a7dde42adf24/resource/aab8e9f9-36d1-42e1-b3ba-e59c79f1d7f0/download/public_150k_plus_240930.csv"
    
    # Smaller files for loans under $150k (split into 10 files)
    DATA_URLS_UNDER_150K = [
        f"https://data.sba.gov/dataset/8aa276e2-6cab-4f86-aca4-a7dde42adf24/resource/738f12a0-5e55-4714-86d9-b6b50078f0bb/download/public_up_to_150k_{i}_240930.csv"
        for i in range(1, 11)
    ]
    
    # Cache directory
    CACHE_DIR = Path("data_cache/ppp")
    
    def __init__(self):
        """Initialize the PPP Loan prospector."""
        self.session = requests.Session()
        self.CACHE_DIR.mkdir(parents=True, exist_ok=True)
    
    def search(
        self,
        states: Optional[List[str]] = None,
        min_loan_amount: float = 0,
        max_loan_amount: float = float('inf'),
        min_jobs: int = 0,
        forgiven_only: bool = False,
        limit: int = 1000,
        progress_callback: Optional[Callable[[int, str], None]] = None
    ) -> List[ProspectRecord]:
        """
        Search for PPP loan recipients.
        
        Args:
            states: List of state codes to filter by
            min_loan_amount: Minimum loan amount
            max_loan_amount: Maximum loan amount
            min_jobs: Minimum jobs reported
            forgiven_only: Only return loans that were forgiven
            limit: Maximum number of records to return
            progress_callback: Optional callback for progress updates
            
        Returns:
            List of ProspectRecord objects
        """
        prospects = []
        states = [s.upper() for s in (states or [])]
        
        if progress_callback:
            progress_callback(5, "Loading PPP loan data...")
        
        try:
            # Load data - start with $150k+ loans (smaller file, better prospects)
            df = self._load_ppp_data(progress_callback)
            
            if df is None or df.empty:
                if progress_callback:
                    progress_callback(0, "Failed to load PPP data")
                return []
            
            if progress_callback:
                progress_callback(50, f"Filtering {len(df):,} loan records...")
            
            # Apply filters
            if states:
                df = df[df['BorrowerState'].isin(states)]
            
            # Loan amount filter
            df = df[df['CurrentApprovalAmount'] >= min_loan_amount]
            if max_loan_amount < float('inf'):
                df = df[df['CurrentApprovalAmount'] <= max_loan_amount]
            
            # Jobs filter
            if min_jobs > 0:
                df = df[df['JobsReported'] >= min_jobs]
            
            # Forgiveness filter
            if forgiven_only:
                df = df[df['ForgivenessAmount'] > 0]
            
            if progress_callback:
                progress_callback(70, f"Processing {len(df):,} matching records...")
            
            # Sort by loan amount (higher = better prospect)
            df = df.sort_values('CurrentApprovalAmount', ascending=False)
            
            # Limit results
            df = df.head(limit)
            
            # Convert to ProspectRecords
            for idx, row in df.iterrows():
                record = self._parse_row(row)
                if record:
                    prospects.append(record)
            
            if progress_callback:
                progress_callback(100, f"Complete: {len(prospects)} PPP recipients found")
                
        except Exception as e:
            if progress_callback:
                progress_callback(0, f"Error: {str(e)}")
        
        return prospects
    
    def _load_ppp_data(self, progress_callback: Optional[Callable] = None) -> Optional[pd.DataFrame]:
        """Load PPP data from cache or download."""
        cache_file = self.CACHE_DIR / "ppp_150k_plus.csv"
        
        # Check cache (valid for 30 days)
        if cache_file.exists():
            cache_age = (pd.Timestamp.now() - pd.Timestamp(cache_file.stat().st_mtime, unit='s')).days
            if cache_age < 30:
                if progress_callback:
                    progress_callback(20, "Loading from cache...")
                try:
                    return pd.read_csv(cache_file, low_memory=False)
                except:
                    pass
        
        # Download fresh data
        if progress_callback:
            progress_callback(10, "Downloading PPP loan data (this may take a minute)...")
        
        try:
            response = self.session.get(self.DATA_URL_150K_PLUS, timeout=120, stream=True)
            response.raise_for_status()
            
            # Save to cache
            with open(cache_file, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            
            if progress_callback:
                progress_callback(40, "Parsing loan data...")
            
            return pd.read_csv(cache_file, low_memory=False)
            
        except Exception as e:
            if progress_callback:
                progress_callback(0, f"Download failed: {str(e)}")
            return None
    
    def _parse_row(self, row: pd.Series) -> Optional[ProspectRecord]:
        """Parse a PPP data row into a ProspectRecord."""
        try:
            # Clean up business name
            business_name = str(row.get('BorrowerName', '')).strip()
            if not business_name or business_name == 'nan':
                return None
            
            # Get loan amount
            loan_amount = float(row.get('CurrentApprovalAmount', 0) or 0)
            
            # Get jobs
            jobs = int(row.get('JobsReported', 0) or 0)
            
            # Get forgiveness info
            forgiven = float(row.get('ForgivenessAmount', 0) or 0)
            
            return ProspectRecord(
                company_name=business_name,
                address=str(row.get('BorrowerAddress', '')).strip() if pd.notna(row.get('BorrowerAddress')) else '',
                city=str(row.get('BorrowerCity', '')).strip() if pd.notna(row.get('BorrowerCity')) else '',
                state=str(row.get('BorrowerState', '')).strip() if pd.notna(row.get('BorrowerState')) else '',
                zip_code=str(row.get('BorrowerZip', ''))[:5] if pd.notna(row.get('BorrowerZip')) else '',
                industry=self.INDUSTRY_NAME,
                source="SBA PPP Program",
                source_id=str(row.get('LoanNumber', '')),
                raw_data={
                    "loan_number": str(row.get('LoanNumber', '')),
                    "loan_amount": loan_amount,
                    "jobs_reported": jobs,
                    "forgiveness_amount": forgiven,
                    "forgiveness_date": str(row.get('ForgivenessDate', '')) if pd.notna(row.get('ForgivenessDate')) else '',
                    "approval_date": str(row.get('DateApproved', '')) if pd.notna(row.get('DateApproved')) else '',
                    "lender": str(row.get('ServicingLenderName', '')) if pd.notna(row.get('ServicingLenderName')) else '',
                    "business_type": str(row.get('BusinessType', '')) if pd.notna(row.get('BusinessType')) else '',
                    "naics_code": str(row.get('NAICSCode', '')) if pd.notna(row.get('NAICSCode')) else '',
                    "race": str(row.get('Race', '')) if pd.notna(row.get('Race')) else '',
                    "gender": str(row.get('Gender', '')) if pd.notna(row.get('Gender')) else '',
                    "veteran": str(row.get('Veteran', '')) if pd.notna(row.get('Veteran')) else '',
                }
            )
        except Exception:
            return None
    
    def get_default_scoring_rules(self):
        """Get default scoring rules for PPP loan recipients."""
        from ..core.scoring import ScoringRule
        
        return [
            # Higher loan amounts indicate larger businesses
            ScoringRule(
                name="large_loan",
                field="raw_data.loan_amount",
                rule_type="range",
                min_value=150000,
                max_value=10000000,
                points=20,
                description="Loan amount $150K+"
            ),
            ScoringRule(
                name="medium_loan",
                field="raw_data.loan_amount", 
                rule_type="range",
                min_value=50000,
                max_value=149999,
                points=10,
                description="Loan amount $50K-$150K"
            ),
            # More jobs = larger operation
            ScoringRule(
                name="significant_employer",
                field="raw_data.jobs_reported",
                rule_type="range",
                min_value=10,
                max_value=500,
                points=15,
                description="10+ employees"
            ),
            # Forgiven loans indicate business survived
            ScoringRule(
                name="loan_forgiven",
                field="raw_data.forgiveness_amount",
                rule_type="range",
                min_value=1,
                max_value=float('inf'),
                points=10,
                description="Loan was forgiven (business survived)"
            ),
            # Has address
            ScoringRule(
                name="has_address",
                field="address",
                rule_type="presence",
                points=5,
                description="Has business address"
            ),
        ]
