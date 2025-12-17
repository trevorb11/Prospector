"""
Restaurant Prospector Module

Searches restaurant health inspection databases from city/county health departments.
Primary data source: NYC DOHMH via Socrata Open Data API.
"""

import os
import requests
from typing import List, Optional, Callable
from dataclasses import dataclass
from datetime import datetime

from prospector.core.base import ProspectRecord, IndustryProspector


@dataclass
class RestaurantRecord:
    """Raw restaurant inspection record."""
    name: str
    dba: str
    address: str
    city: str
    state: str
    zipcode: str
    phone: str
    cuisine: str
    grade: str
    score: int
    inspection_date: str
    violation_code: str
    violation_desc: str
    boro: str


class RestaurantProspector(IndustryProspector):
    """
    Prospector for restaurants using health department inspection data.
    
    Primary source: NYC DOHMH Restaurant Inspection Results via Socrata.
    """
    
    INDUSTRY_NAME = "restaurants"
    
    NYC_ENDPOINT = "https://data.cityofnewyork.us/resource/43nn-pn8j.json"
    NYS_ENDPOINT = "https://health.data.ny.gov/resource/cnih-y5dw.json"
    
    BOROUGH_MAP = {
        "MANHATTAN": "Manhattan, NY",
        "BROOKLYN": "Brooklyn, NY", 
        "QUEENS": "Queens, NY",
        "BRONX": "Bronx, NY",
        "STATEN ISLAND": "Staten Island, NY"
    }
    
    def __init__(self):
        self.app_token = os.environ.get("SOCRATA_APP_TOKEN", "")
        
    def search(
        self,
        boroughs: Optional[List[str]] = None,
        cuisines: Optional[List[str]] = None,
        min_grade: str = "A",
        grades: Optional[List[str]] = None,
        limit: int = 1000,
        progress_callback: Optional[Callable[[int, str], None]] = None
    ) -> List[ProspectRecord]:
        """
        Search NYC restaurant inspection database.
        
        Args:
            boroughs: List of NYC boroughs to search (MANHATTAN, BROOKLYN, etc.)
            cuisines: List of cuisine types to filter by
            min_grade: Minimum inspection grade (A, B, C)
            grades: Specific grades to include
            limit: Maximum records to return
            progress_callback: Function to report progress
            
        Returns:
            List of ProspectRecord objects
        """
        if progress_callback:
            progress_callback(5, "Connecting to NYC Health Department database...")
        
        headers = {}
        if self.app_token:
            headers["X-App-Token"] = self.app_token
        
        where_clauses = []
        
        if grades:
            grade_list = "','".join(grades)
            where_clauses.append(f"grade in ('{grade_list}')")
        elif min_grade:
            valid_grades = self._get_valid_grades(min_grade)
            if valid_grades:
                grade_list = "','".join(valid_grades)
                where_clauses.append(f"grade in ('{grade_list}')")
        
        if boroughs:
            boro_list = "','".join([b.upper() for b in boroughs])
            where_clauses.append(f"boro in ('{boro_list}')")
            
        if cuisines:
            cuisine_conditions = " OR ".join([f"cuisine_description LIKE '%{c}%'" for c in cuisines])
            where_clauses.append(f"({cuisine_conditions})")
        
        where_clause = " AND ".join(where_clauses) if where_clauses else None
        
        params = {
            "$limit": min(limit * 3, 50000),
            "$order": "inspection_date DESC",
            "$select": "camis,dba,boro,building,street,zipcode,phone,cuisine_description,inspection_date,grade,score,violation_code,violation_description"
        }
        
        if where_clause:
            params["$where"] = where_clause
        
        if progress_callback:
            progress_callback(15, "Fetching restaurant inspection records...")
        
        try:
            response = requests.get(
                self.NYC_ENDPOINT,
                headers=headers,
                params=params,
                timeout=60
            )
            response.raise_for_status()
            raw_data = response.json()
        except requests.exceptions.RequestException as e:
            if progress_callback:
                progress_callback(100, f"Error: {str(e)}")
            return []
        
        if progress_callback:
            progress_callback(50, f"Processing {len(raw_data)} inspection records...")
        
        seen_restaurants = {}
        
        for record in raw_data:
            camis = record.get("camis", "")
            if not camis:
                continue
                
            if camis not in seen_restaurants:
                seen_restaurants[camis] = {
                    "camis": camis,
                    "dba": record.get("dba", ""),
                    "boro": record.get("boro", ""),
                    "building": record.get("building", ""),
                    "street": record.get("street", ""),
                    "zipcode": record.get("zipcode", ""),
                    "phone": record.get("phone", ""),
                    "cuisine": record.get("cuisine_description", ""),
                    "grade": record.get("grade", ""),
                    "score": record.get("score", 0),
                    "inspection_date": record.get("inspection_date", ""),
                    "violations": []
                }
            
            violation = record.get("violation_description", "")
            if violation and violation not in seen_restaurants[camis]["violations"]:
                seen_restaurants[camis]["violations"].append(violation)
        
        if progress_callback:
            progress_callback(70, f"Found {len(seen_restaurants)} unique restaurants...")
        
        prospects = []
        for camis, rest in seen_restaurants.items():
            if len(prospects) >= limit:
                break
                
            phone = rest.get("phone", "")
            if phone:
                phone = self._format_phone(phone)
            
            address = f"{rest.get('building', '')} {rest.get('street', '')}".strip()
            boro = rest.get("boro", "")
            city = self.BOROUGH_MAP.get(boro.upper(), boro)
            
            grade = rest.get("grade", "")
            score = rest.get("score", 0)
            try:
                score = int(score) if score else 0
            except (ValueError, TypeError):
                score = 0
            
            cuisine = rest.get("cuisine", "")
            violations = rest.get("violations", [])
            
            prospect = ProspectRecord(
                company_name=rest.get("dba", "Unknown"),
                address=address,
                city=city.split(",")[0] if city else "",
                state="NY",
                zipcode=rest.get("zipcode", ""),
                phone=phone,
                contact_name="",
                email="",
                industry="Restaurant",
                business_type=cuisine,
                employee_count=0,
                annual_revenue=0,
                years_in_business=0,
                score=self._calculate_score(grade, score, phone, violations),
                source="NYC DOHMH",
                source_id=camis,
                raw_data={
                    "grade": grade,
                    "inspection_score": score,
                    "cuisine": cuisine,
                    "violation_count": len(violations),
                    "last_inspection": rest.get("inspection_date", "")
                }
            )
            prospects.append(prospect)
        
        prospects.sort(key=lambda x: x.score, reverse=True)
        
        if progress_callback:
            progress_callback(100, f"Completed - {len(prospects)} restaurants found")
        
        return prospects
    
    def _get_valid_grades(self, min_grade: str) -> List[str]:
        """Get list of valid grades at or above minimum."""
        grade_order = ["A", "B", "C"]
        try:
            idx = grade_order.index(min_grade.upper())
            return grade_order[:idx + 1]
        except ValueError:
            return ["A", "B", "C"]
    
    def _format_phone(self, phone: str) -> str:
        """Format phone number."""
        digits = "".join(filter(str.isdigit, str(phone)))
        if len(digits) == 10:
            return f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"
        elif len(digits) == 11 and digits[0] == "1":
            return f"({digits[1:4]}) {digits[4:7]}-{digits[7:]}"
        return phone
    
    def _calculate_score(self, grade: str, inspection_score: int, phone: str, violations: List[str]) -> int:
        """Calculate prospect score based on restaurant data."""
        score = 50
        
        if grade == "A":
            score += 25
        elif grade == "B":
            score += 15
        elif grade == "C":
            score += 5
        
        if inspection_score:
            if inspection_score <= 13:
                score += 15
            elif inspection_score <= 27:
                score += 10
            elif inspection_score <= 40:
                score += 5
        
        if phone:
            score += 10
        
        violation_count = len(violations)
        if violation_count == 0:
            score += 5
        elif violation_count > 5:
            score -= 5
        
        return min(100, max(0, score))
    
    def get_cuisines(self) -> List[str]:
        """Get list of common cuisine types for filtering."""
        return [
            "American",
            "Chinese",
            "Italian",
            "Mexican",
            "Japanese",
            "Thai",
            "Indian",
            "Pizza",
            "Bakery",
            "Cafe",
            "Deli",
            "Seafood",
            "Steak",
            "BBQ",
            "Latin",
            "Caribbean",
            "Korean",
            "Vietnamese",
            "Mediterranean",
            "Greek"
        ]
