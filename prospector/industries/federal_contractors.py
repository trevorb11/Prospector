"""
Federal Contractors Industry Prospector

Fetches business data from SAM.gov Entity API for federal government contractors.
These are businesses registered to do business with the federal government.

Note: SAM.gov API requires a free API key from sam.gov
"""

import os
import requests
from typing import List, Optional, Dict, Any, Callable
from dataclasses import dataclass
from datetime import datetime

from ..core.base import ProspectRecord, IndustryProspector


class FederalContractorProspector(IndustryProspector):
    """Prospector for SAM.gov federal contractor registry."""
    
    INDUSTRY_NAME = "federal_contractors"
    DISPLAY_NAME = "Federal Contractors (SAM.gov)"
    
    # SAM.gov Entity API endpoint
    BASE_URL = "https://api.sam.gov/entity-information/v3/entities"
    
    # Business types that are good MCA prospects
    BUSINESS_TYPES = [
        "2L",  # Limited Liability Company
        "2J",  # S Corporation  
        "2K",  # C Corporation
        "8H",  # Small Business
    ]
    
    def __init__(self, api_key: Optional[str] = None):
        """
        Initialize the Federal Contractor prospector.
        
        Args:
            api_key: SAM.gov API key. If not provided, uses SAM_API_KEY env var.
        """
        self.api_key = api_key or os.environ.get("SAM_API_KEY", "")
        self.session = requests.Session()
        if self.api_key:
            self.session.headers.update({"X-Api-Key": self.api_key})
    
    def search(
        self,
        states: Optional[List[str]] = None,
        naics_codes: Optional[List[str]] = None,
        small_business_only: bool = True,
        active_only: bool = True,
        limit: int = 1000,
        progress_callback: Optional[Callable[[int, str], None]] = None
    ) -> List[ProspectRecord]:
        """
        Search for federal contractors.
        
        Args:
            states: List of state codes to filter by (e.g., ['CA', 'TX'])
            naics_codes: List of NAICS codes to filter by
            small_business_only: If True, only return small businesses
            active_only: If True, only return active registrations
            limit: Maximum number of records to return
            progress_callback: Optional callback for progress updates
            
        Returns:
            List of ProspectRecord objects
        """
        if not self.api_key:
            if progress_callback:
                progress_callback(0, "Error: SAM_API_KEY not configured")
            return []
        
        prospects = []
        states = states or []
        
        if progress_callback:
            progress_callback(5, "Connecting to SAM.gov API...")
        
        try:
            # Build query parameters
            params = {
                "registrationStatus": "A" if active_only else None,
                "purposeOfRegistrationCode": "Z2",  # All awards
                "includeSections": "entityRegistration,coreData,pointsOfContact",
                "page": 0,
                "size": min(limit, 100)  # API max is 100 per page
            }
            
            # Add state filter
            if states:
                params["physicalAddressStateCode"] = ",".join(states)
            
            # Add NAICS filter
            if naics_codes:
                params["naicsCode"] = ",".join(naics_codes)
            
            # Add small business filter
            if small_business_only:
                params["sbaBusinessTypeCode"] = "27"  # Small Business
            
            # Remove None values
            params = {k: v for k, v in params.items() if v is not None}
            
            if progress_callback:
                progress_callback(10, f"Searching federal contractors...")
            
            total_fetched = 0
            page = 0
            
            while total_fetched < limit:
                params["page"] = page
                
                response = self.session.get(self.BASE_URL, params=params, timeout=30)
                
                if response.status_code == 403:
                    if progress_callback:
                        progress_callback(0, "API key invalid or expired")
                    break
                
                response.raise_for_status()
                data = response.json()
                
                entities = data.get("entityData", [])
                if not entities:
                    break
                
                for entity in entities:
                    if total_fetched >= limit:
                        break
                    
                    record = self._parse_entity(entity)
                    if record:
                        prospects.append(record)
                        total_fetched += 1
                
                # Update progress
                progress = min(90, 10 + int((total_fetched / limit) * 80))
                if progress_callback:
                    progress_callback(progress, f"Found {total_fetched} contractors...")
                
                # Check if more pages available
                total_records = data.get("totalRecords", 0)
                if total_fetched >= total_records:
                    break
                
                page += 1
            
            if progress_callback:
                progress_callback(100, f"Complete: {len(prospects)} contractors found")
                
        except requests.exceptions.RequestException as e:
            if progress_callback:
                progress_callback(0, f"API error: {str(e)}")
        
        return prospects
    
    def _parse_entity(self, entity: Dict[str, Any]) -> Optional[ProspectRecord]:
        """Parse a SAM.gov entity into a ProspectRecord."""
        try:
            reg = entity.get("entityRegistration", {})
            core = entity.get("coreData", {})
            contacts = entity.get("pointsOfContact", {})
            
            # Get physical address
            phys_addr = core.get("physicalAddress", {})
            
            # Get primary contact
            govt_contact = contacts.get("governmentBusinessPOC", {})
            if not govt_contact:
                govt_contact = contacts.get("electronicBusinessPOC", {})
            
            # Build address string
            address_parts = [
                phys_addr.get("addressLine1", ""),
                phys_addr.get("addressLine2", "")
            ]
            address = ", ".join(filter(None, address_parts))
            
            # Get business info
            business_info = core.get("businessInformation", {})
            
            # Extract entity start date for years in business
            entity_info = core.get("entityInformation", {})
            start_date_str = entity_info.get("entityStartDate", "")
            years_in_business = None
            if start_date_str:
                try:
                    start_date = datetime.strptime(start_date_str[:10], "%Y-%m-%d")
                    years_in_business = (datetime.now() - start_date).days // 365
                except:
                    pass
            
            return ProspectRecord(
                company_name=reg.get("legalBusinessName", ""),
                dba_name=reg.get("dbaName", ""),
                address=address,
                city=phys_addr.get("city", ""),
                state=phys_addr.get("stateOrProvinceCode", ""),
                zip_code=phys_addr.get("zipCode", "")[:5] if phys_addr.get("zipCode") else "",
                phone=govt_contact.get("USPhone", "") or govt_contact.get("nonUSPhone", ""),
                email=govt_contact.get("email", ""),
                contact_name=f"{govt_contact.get('firstName', '')} {govt_contact.get('lastName', '')}".strip(),
                years_in_business=years_in_business,
                industry=self.INDUSTRY_NAME,
                source="SAM.gov",
                source_id=reg.get("ueiSAM", ""),
                raw_data={
                    "uei": reg.get("ueiSAM", ""),
                    "cage_code": reg.get("cageCode", ""),
                    "registration_status": reg.get("registrationStatus", ""),
                    "purpose_of_registration": reg.get("purposeOfRegistrationDesc", ""),
                    "entity_type": business_info.get("entityStructureDesc", ""),
                    "naics_codes": [n.get("naicsCode") for n in core.get("naicsCodeList", [])],
                    "small_business": business_info.get("sbaBusinessTypeDesc", []),
                    "expiration_date": reg.get("registrationExpirationDate", ""),
                }
            )
        except Exception as e:
            return None
    
    def get_default_scoring_rules(self):
        """Get default scoring rules for federal contractors."""
        from ..core.scoring import ScoringRule
        
        return [
            # Active registration is important
            ScoringRule(
                name="active_registration",
                field="raw_data.registration_status",
                rule_type="equals",
                value="Active",
                points=15,
                description="Active SAM.gov registration"
            ),
            # Years in business
            ScoringRule(
                name="established_business",
                field="years_in_business",
                rule_type="range",
                min_value=3,
                max_value=50,
                points=10,
                description="3+ years in business"
            ),
            # Has contact info
            ScoringRule(
                name="has_phone",
                field="phone",
                rule_type="presence",
                points=10,
                description="Has phone number"
            ),
            ScoringRule(
                name="has_email",
                field="email",
                rule_type="presence",
                points=10,
                description="Has email address"
            ),
            ScoringRule(
                name="has_contact_name",
                field="contact_name",
                rule_type="presence",
                points=5,
                description="Has contact name"
            ),
        ]
