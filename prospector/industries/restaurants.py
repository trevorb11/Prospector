"""
Restaurant Prospector
====================

Finds restaurant prospects using health inspection databases
and business registries.

Restaurants are excellent financing prospects because they need:
- Equipment financing (ovens, refrigeration, POS systems)
- Leasehold improvements
- Working capital for inventory/operations
- Expansion financing for additional locations
"""

import requests
from typing import Any, Dict, List, Optional
from datetime import datetime

from ..core.base import IndustryProspector, ProspectRecord
from ..core.scoring import RuleType


class RestaurantProspector(IndustryProspector):
    """
    Prospector for restaurants and food service businesses.

    Uses health inspection databases and business registries to find
    restaurants that may need financing.
    """

    # Restaurant types with different equipment needs
    RESTAURANT_TYPES = {
        "full_service": "Full Service Restaurant",
        "fast_food": "Fast Food/Quick Service",
        "cafe": "Cafe/Coffee Shop",
        "bakery": "Bakery",
        "bar": "Bar/Nightclub",
        "catering": "Catering Company",
        "food_truck": "Food Truck",
        "pizzeria": "Pizzeria",
        "deli": "Deli/Sandwich Shop",
    }

    # Keywords to classify restaurant types
    TYPE_KEYWORDS = {
        "pizzeria": ["pizza", "pizzeria"],
        "bakery": ["bakery", "bake shop", "pastry", "donut", "doughnut", "bagel"],
        "cafe": ["cafe", "coffee", "espresso", "tea house", "starbucks"],
        "bar": ["bar", "pub", "tavern", "nightclub", "lounge", "brewery", "taproom"],
        "fast_food": ["mcdonald", "burger king", "wendy", "taco bell", "kfc", "subway", "chipotle", "fast food", "drive thru"],
        "deli": ["deli", "sandwich", "sub shop", "hoagie"],
        "catering": ["catering", "banquet"],
        "food_truck": ["food truck", "mobile food"],
    }

    # Socrata datasets for different cities
    HEALTH_INSPECTION_DATASETS = {
        "NYC": {
            "domain": "data.cityofnewyork.us",
            "dataset_id": "43nn-pn8j",
            "name_field": "dba",
            "address_field": "building",
            "city_field": "boro",
            "phone_field": "phone",
            "cuisine_field": "cuisine_description",
        },
        "Chicago": {
            "domain": "data.cityofchicago.org",
            "dataset_id": "4ijn-s7e5",
            "name_field": "dba_name",
            "address_field": "address",
            "city_field": "city",
            "phone_field": None,
            "cuisine_field": "facility_type",
        },
        "Austin": {
            "domain": "data.austintexas.gov",
            "dataset_id": "ecmv-9xxi",
            "name_field": "restaurant_name",
            "address_field": "address",
            "city_field": "city",
            "phone_field": None,
            "cuisine_field": None,
        },
    }

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize the restaurant prospector.

        Config options:
            target_cities: List of cities to search (NYC, Chicago, Austin, etc.)
            target_states: List of states for business registry search
            restaurant_types: Types to include
            min_score: Minimum health inspection score (where available)
            limit_per_city: Max records per city
        """
        self.config = config or {}
        self.target_cities = self.config.get("target_cities", ["NYC"])
        self.target_states = self.config.get("target_states", [])
        self.restaurant_types = self.config.get("restaurant_types", None)
        self.limit_per_city = self.config.get("limit_per_city", 500)
        self._prospects: List[ProspectRecord] = []

    def get_industry_name(self) -> str:
        return "Restaurants"

    def fetch_prospects(self) -> List[Dict[str, Any]]:
        """Fetch restaurant data from health inspection databases."""
        print(f"\nFetching restaurant prospects...")
        print(f"  Cities: {', '.join(self.target_cities)}")

        all_records = []

        for city in self.target_cities:
            if city.upper() in self.HEALTH_INSPECTION_DATASETS:
                city_records = self._fetch_city_data(city.upper())
                all_records.extend(city_records)
            else:
                # Fall back to business registry search
                state_records = self._fetch_from_registry(city)
                all_records.extend(state_records)

        print(f"\nTotal raw records: {len(all_records)}")
        return all_records

    def _fetch_city_data(self, city: str) -> List[Dict[str, Any]]:
        """Fetch restaurant data from a city's health inspection database."""
        records = []
        config = self.HEALTH_INSPECTION_DATASETS.get(city)

        if not config:
            return records

        try:
            # Use Socrata API
            url = f"https://{config['domain']}/resource/{config['dataset_id']}.json"

            params = {
                "$limit": self.limit_per_city,
                "$order": ":id",
            }

            # For NYC, get recent inspections with good grades
            if city == "NYC":
                params["$where"] = "grade IN ('A', 'B', 'C') AND inspection_date > '2023-01-01'"
                params["$order"] = "inspection_date DESC"

            response = requests.get(url, params=params, timeout=30)

            if response.status_code == 200:
                data = response.json()
                seen_names = set()

                for item in data:
                    # Get restaurant name
                    name = item.get(config["name_field"], "")
                    if not name or name.upper() in seen_names:
                        continue
                    seen_names.add(name.upper())

                    # Skip chains we want to exclude (too big)
                    if self._is_major_chain(name):
                        continue

                    record = {
                        "restaurant_name": name,
                        "address": item.get(config["address_field"], ""),
                        "city": city if city != "NYC" else item.get(config["city_field"], "NYC"),
                        "state": self._city_to_state(city),
                        "phone": item.get(config["phone_field"], "") if config["phone_field"] else "",
                        "cuisine": item.get(config["cuisine_field"], "") if config["cuisine_field"] else "",
                        "grade": item.get("grade", ""),
                        "score": item.get("score", ""),
                        "inspection_date": item.get("inspection_date", ""),
                        "source": f"{city} Health Department",
                    }
                    records.append(record)

                    if len(records) >= self.limit_per_city:
                        break

            print(f"  Fetching {city}... {len(records)} restaurants found")

        except requests.RequestException as e:
            print(f"    Warning: Error fetching {city}: {e}")

        return records

    def _fetch_from_registry(self, location: str) -> List[Dict[str, Any]]:
        """Fetch restaurants from business registry when health data unavailable."""
        records = []
        seen_companies = set()

        # Determine if it's a city or state
        state = location if len(location) == 2 else None

        search_terms = ["restaurant", "cafe", "pizzeria", "grill", "diner", "bistro"]

        state_codes = {
            "FL": "us_fl", "TX": "us_tx", "CA": "us_ca", "NY": "us_ny",
            "GA": "us_ga", "NC": "us_nc", "AZ": "us_az", "CO": "us_co",
        }

        jurisdiction = state_codes.get(state.upper()) if state else None

        for term in search_terms:
            if len(records) >= self.limit_per_city:
                break

            try:
                url = "https://api.opencorporates.com/v0.4/companies/search"
                params = {
                    "q": term,
                    "per_page": 50,
                    "current_status": "Active",
                }
                if jurisdiction:
                    params["jurisdiction_code"] = jurisdiction

                response = requests.get(url, params=params, timeout=15)

                if response.status_code == 200:
                    data = response.json()
                    companies = data.get("results", {}).get("companies", [])

                    for item in companies:
                        company = item.get("company", {})
                        name = company.get("name", "")

                        if name.upper() in seen_companies:
                            continue
                        seen_companies.add(name.upper())

                        if not self._is_restaurant(name):
                            continue

                        if self._is_major_chain(name):
                            continue

                        record = {
                            "restaurant_name": name,
                            "address": company.get("registered_address_in_full", ""),
                            "city": location,
                            "state": state or "",
                            "incorporation_date": company.get("incorporation_date"),
                            "source": "Business Registry",
                        }
                        records.append(record)

                        if len(records) >= self.limit_per_city:
                            break

            except requests.RequestException:
                continue

        print(f"  Fetching {location}... {len(records)} restaurants found")
        return records

    def _city_to_state(self, city: str) -> str:
        """Map city to state abbreviation."""
        city_states = {
            "NYC": "NY",
            "Chicago": "IL",
            "Austin": "TX",
            "Los Angeles": "CA",
            "Miami": "FL",
        }
        return city_states.get(city, "")

    def _is_restaurant(self, name: str) -> bool:
        """Check if company name looks like a restaurant."""
        name_lower = name.lower()

        indicators = [
            "restaurant", "cafe", "coffee", "pizza", "grill", "diner",
            "bistro", "kitchen", "eatery", "food", "catering", "bakery",
            "bar", "pub", "tavern", "sushi", "thai", "chinese", "mexican",
            "italian", "steakhouse", "bbq", "barbecue", "seafood", "deli",
        ]

        return any(ind in name_lower for ind in indicators)

    def _is_major_chain(self, name: str) -> bool:
        """Check if restaurant is a major chain (too big for our target market)."""
        name_lower = name.lower()

        major_chains = [
            "mcdonald", "burger king", "wendy's", "taco bell", "kfc",
            "pizza hut", "domino", "papa john", "subway", "chipotle",
            "starbucks", "dunkin", "panera", "chick-fil-a", "popeye",
            "arby", "sonic", "five guys", "shake shack", "in-n-out",
        ]

        return any(chain in name_lower for chain in major_chains)

    def _determine_restaurant_type(self, name: str, cuisine: str = "") -> str:
        """Determine restaurant type from name and cuisine."""
        text = f"{name} {cuisine}".lower()

        for rest_type, keywords in self.TYPE_KEYWORDS.items():
            if any(kw in text for kw in keywords):
                return self.RESTAURANT_TYPES.get(rest_type, "Restaurant")

        # Default classification
        if cuisine:
            return f"{cuisine} Restaurant"

        return "Full Service Restaurant"

    def parse_record(self, raw: Dict[str, Any]) -> ProspectRecord:
        """Parse raw restaurant data into a ProspectRecord."""
        name = raw.get("restaurant_name", "Unknown")
        cuisine = raw.get("cuisine", "")
        restaurant_type = self._determine_restaurant_type(name, cuisine)

        # Calculate years in business if we have inspection history
        years = None
        inc_date = raw.get("incorporation_date")
        if inc_date:
            try:
                inc_year = int(str(inc_date)[:4])
                years = datetime.now().year - inc_year
            except (ValueError, TypeError):
                pass

        # Parse health inspection grade/score
        grade = raw.get("grade", "")
        score = raw.get("score", "")

        return ProspectRecord(
            company_name=name,
            phone=raw.get("phone", ""),
            address=raw.get("address", ""),
            city=raw.get("city", ""),
            state=raw.get("state", ""),
            years_in_business=years,
            industry_data={
                "Restaurant Type": restaurant_type,
                "Cuisine": cuisine,
                "Health Grade": grade,
                "Inspection Score": score,
                "Last Inspection": raw.get("inspection_date", ""),
            },
        )

    def get_scoring_rules(self) -> List[Dict[str, Any]]:
        """Return scoring rules for restaurants."""
        return [
            # Base score
            {
                "name": "base_score",
                "field": "company_name",
                "rule_type": RuleType.PRESENCE,
                "points": 50,
            },
            # Full service restaurants (more equipment)
            {
                "name": "full_service",
                "field": "industry_data.Restaurant Type",
                "rule_type": RuleType.CONTAINS,
                "value": "Full Service",
                "points": 20,
            },
            # Bakeries (specialized equipment)
            {
                "name": "bakery",
                "field": "industry_data.Restaurant Type",
                "rule_type": RuleType.CONTAINS,
                "value": "Bakery",
                "points": 20,
            },
            # Pizzerias (ovens, equipment)
            {
                "name": "pizzeria",
                "field": "industry_data.Restaurant Type",
                "rule_type": RuleType.CONTAINS,
                "value": "Pizza",
                "points": 15,
            },
            # Catering (vehicles, equipment)
            {
                "name": "catering",
                "field": "industry_data.Restaurant Type",
                "rule_type": RuleType.CONTAINS,
                "value": "Catering",
                "points": 20,
            },
            # Bar/Nightclub
            {
                "name": "bar",
                "field": "industry_data.Restaurant Type",
                "rule_type": RuleType.CONTAINS,
                "value": "Bar",
                "points": 15,
            },
            # Good health grade (A)
            {
                "name": "grade_a",
                "field": "industry_data.Health Grade",
                "rule_type": RuleType.EQUALS,
                "value": "A",
                "points": 15,
            },
            # Decent health grade (B)
            {
                "name": "grade_b",
                "field": "industry_data.Health Grade",
                "rule_type": RuleType.EQUALS,
                "value": "B",
                "points": 10,
            },
            # Has phone
            {
                "name": "has_phone",
                "field": "phone",
                "rule_type": RuleType.PRESENCE,
                "points": 10,
            },
            # Established business
            {
                "name": "established",
                "field": "years_in_business",
                "rule_type": RuleType.RANGE,
                "min_value": 3,
                "max_value": 100,
                "points": 15,
            },
        ]


def search_restaurants(city: str, cuisine: str = None, limit: int = 50) -> List[Dict[str, Any]]:
    """
    Search for restaurants in a city.

    Args:
        city: City name (NYC, Chicago, Austin, or state abbreviation)
        cuisine: Optional cuisine type filter
        limit: Maximum results

    Returns:
        List of restaurant records
    """
    config = {
        "target_cities": [city],
        "limit_per_city": limit,
    }

    prospector = RestaurantProspector(config)
    records = prospector.fetch_prospects()

    # Filter by cuisine if specified
    if cuisine:
        cuisine_lower = cuisine.lower()
        records = [r for r in records if cuisine_lower in r.get("cuisine", "").lower()]

    return records


def get_restaurants_by_type(city: str, restaurant_type: str, limit: int = 50) -> List[Dict[str, Any]]:
    """
    Get restaurants of a specific type in a city.

    Args:
        city: City name
        restaurant_type: Type (pizza, cafe, bar, etc.)
        limit: Maximum results

    Returns:
        List of matching restaurants
    """
    config = {
        "target_cities": [city],
        "limit_per_city": limit * 3,  # Get more to filter
    }

    prospector = RestaurantProspector(config)
    records = prospector.fetch_prospects()

    # Filter by type
    type_lower = restaurant_type.lower()
    filtered = []

    for r in records:
        name = r.get("restaurant_name", "").lower()
        cuisine = r.get("cuisine", "").lower()

        if type_lower in name or type_lower in cuisine:
            filtered.append(r)

        if len(filtered) >= limit:
            break

    return filtered
