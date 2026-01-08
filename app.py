#!/usr/bin/env python3
"""
Prospector Web Application
==========================

Flask-based web interface for the Prospector tool.
Designed to run on Replit and other cloud platforms.
"""

import os
import json
import uuid
import threading
import time
from datetime import datetime
from pathlib import Path

from flask import (
    Flask,
    render_template,
    request,
    jsonify,
    send_file,
    Response,
)

# Initialize Flask app
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "prospector-secret-key-change-in-production")
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50 MB max file upload

# Configuration
OUTPUT_DIR = Path("output")
OUTPUT_DIR.mkdir(exist_ok=True)

# Store for background jobs
jobs = {}


class ProspectorJob:
    """Represents a background prospector job."""

    def __init__(self, job_id: str, config: dict):
        self.job_id = job_id
        self.config = config
        self.status = "pending"
        self.progress = 0
        self.progress_message = "Initializing..."
        self.result = None
        self.error = None
        self.output_file = None
        self.hot_file = None
        self.started_at = None
        self.completed_at = None
        self.stats = {}

    def to_dict(self):
        return {
            "job_id": self.job_id,
            "status": self.status,
            "progress": self.progress,
            "progress_message": self.progress_message,
            "error": self.error,
            "output_file": self.output_file,
            "hot_file": self.hot_file,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "stats": self.stats,
        }


def run_prospector_job(job: ProspectorJob):
    """Run the prospector in a background thread."""
    try:
        job.status = "running"
        job.started_at = datetime.now()
        job.progress_message = "Starting prospect search..."

        from prospector.industries.trucking import TruckingProspector

        # Create prospector with config
        config = {
            "target_states": job.config.get("states", ["FL"]),
            "min_power_units": job.config.get("min_trucks", 1),
            "max_power_units": job.config.get("max_trucks", 50),
            "max_records_per_state": job.config.get("max_records", 5000),
            "app_token": os.environ.get("SOCRATA_APP_TOKEN"),
        }

        prospector = TruckingProspector(config)

        # Custom fetch with progress updates
        all_records = []
        states = config["target_states"]
        total_states = len(states)

        for i, state in enumerate(states):
            job.progress = int((i / total_states) * 80)
            job.progress_message = f"Fetching {state}... ({i+1}/{total_states})"

            state_records = prospector._fetch_state_data(state)
            all_records.extend(state_records)
            time.sleep(0.5)  # Rate limiting

        job.progress = 80
        job.progress_message = f"Processing {len(all_records)} records..."

        # Process records
        prospects = []
        for raw in all_records:
            try:
                record = prospector.parse_record(raw)
                record.source = prospector.get_industry_name()
                prospects.append(record)
            except Exception:
                continue

        # Score prospects
        job.progress = 90
        job.progress_message = "Scoring prospects..."

        from prospector.core.scoring import ScoringEngine
        scoring_engine = ScoringEngine(prospector.get_scoring_rules())
        prospects = [scoring_engine.score(r) for r in prospects]
        prospects.sort(key=lambda x: x.prospect_score, reverse=True)

        prospector._prospects = prospects

        # Export to CSV
        job.progress = 95
        job.progress_message = "Generating output files..."

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_filename = f"prospects_{timestamp}.csv"
        output_path = OUTPUT_DIR / output_filename

        df = prospector.to_dataframe()
        df.to_csv(output_path, index=False)
        job.output_file = output_filename

        # Export hot prospects (only if we have data with Score column)
        if not df.empty and "Score" in df.columns:
            hot_df = df[df["Score"] >= 70]
            if not hot_df.empty:
                hot_filename = f"prospects_{timestamp}_HOT.csv"
                hot_path = OUTPUT_DIR / hot_filename
                hot_df.to_csv(hot_path, index=False)
                job.hot_file = hot_filename

        # Get summary stats
        if not df.empty:
            job.stats = prospector.get_summary()
        else:
            job.stats = {"total": 0, "message": "No prospects found matching criteria"}

        job.progress = 100
        job.progress_message = "Complete!"
        job.status = "completed"
        job.completed_at = datetime.now()

    except Exception as e:
        job.status = "failed"
        job.error = str(e)
        job.completed_at = datetime.now()


def run_lookup_job(job: ProspectorJob):
    """Run a DOT lookup job."""
    try:
        job.status = "running"
        job.started_at = datetime.now()
        job.progress_message = "Looking up company..."

        from prospector.industries.trucking import lookup_by_dot

        dot_number = job.config.get("dot_number")
        app_token = os.environ.get("SOCRATA_APP_TOKEN")

        result = lookup_by_dot(dot_number, app_token=app_token)

        if result:
            job.result = result
            job.status = "completed"
            job.progress = 100
            job.progress_message = "Found!"
        else:
            job.status = "completed"
            job.progress = 100
            job.progress_message = "No company found"
            job.result = None

        job.completed_at = datetime.now()

    except Exception as e:
        job.status = "failed"
        job.error = str(e)
        job.completed_at = datetime.now()


def run_search_job(job: ProspectorJob):
    """Run a name search job."""
    try:
        job.status = "running"
        job.started_at = datetime.now()
        job.progress_message = "Searching..."

        from prospector.industries.trucking import search_by_name

        company_name = job.config.get("company_name")
        state = job.config.get("state")
        limit = job.config.get("limit", 25)
        app_token = os.environ.get("SOCRATA_APP_TOKEN")

        results = search_by_name(company_name, state=state, limit=limit, app_token=app_token)

        job.result = results
        job.stats = {"count": len(results)}
        job.status = "completed"
        job.progress = 100
        job.progress_message = f"Found {len(results)} results"
        job.completed_at = datetime.now()

    except Exception as e:
        job.status = "failed"
        job.error = str(e)
        job.completed_at = datetime.now()


def run_city_job(job: ProspectorJob):
    """Run a city search job."""
    try:
        job.status = "running"
        job.started_at = datetime.now()
        job.progress_message = "Fetching carriers..."

        from prospector.industries.trucking import get_carriers_by_city

        city = job.config.get("city")
        state = job.config.get("state")
        min_trucks = job.config.get("min_trucks", 1)
        max_trucks = job.config.get("max_trucks", 50)
        app_token = os.environ.get("SOCRATA_APP_TOKEN")

        results = get_carriers_by_city(
            city=city,
            state=state,
            min_trucks=min_trucks,
            max_trucks=max_trucks,
            app_token=app_token,
        )

        # Export to CSV if results
        if results:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"carriers_{city}_{state}_{timestamp}.csv"
            filepath = OUTPUT_DIR / filename

            import pandas as pd
            df = pd.DataFrame(results)
            df.to_csv(filepath, index=False)
            job.output_file = filename

        job.result = results[:50]  # Return first 50 for display
        job.stats = {"count": len(results)}
        job.status = "completed"
        job.progress = 100
        job.progress_message = f"Found {len(results)} carriers"
        job.completed_at = datetime.now()

    except Exception as e:
        job.status = "failed"
        job.error = str(e)
        job.completed_at = datetime.now()


def run_healthcare_job(job: ProspectorJob):
    """Run a healthcare prospect search job."""
    try:
        job.status = "running"
        job.started_at = datetime.now()
        job.progress_message = "Starting healthcare prospect search..."

        from prospector.industries.healthcare import HealthcareProspector

        config = {
            "target_states": job.config.get("states", ["FL"]),
            "organization_only": job.config.get("organizations_only", True),
            "entity_types": ["2"] if job.config.get("organizations_only", True) else ["1", "2"],
            "limit_per_state": job.config.get("limit_per_state", 500),
        }

        prospector = HealthcareProspector(config)

        # Fetch with progress updates
        all_records = []
        states = config["target_states"]
        total_states = len(states)

        for i, state in enumerate(states):
            job.progress = int((i / total_states) * 80)
            job.progress_message = f"Fetching {state}... ({i+1}/{total_states})"

            state_records = prospector._fetch_state_data(state)
            all_records.extend(state_records)
            time.sleep(0.3)

        job.progress = 80
        job.progress_message = f"Processing {len(all_records)} records..."

        # Process records
        prospects = []
        for raw in all_records:
            try:
                record = prospector.parse_record(raw)
                record.source = prospector.get_industry_name()
                prospects.append(record)
            except Exception:
                continue

        # Score prospects
        job.progress = 90
        job.progress_message = "Scoring prospects..."

        from prospector.core.scoring import ScoringEngine
        scoring_engine = ScoringEngine(prospector.get_scoring_rules())
        prospects = [scoring_engine.score(r) for r in prospects]
        prospects.sort(key=lambda x: x.prospect_score, reverse=True)

        prospector._prospects = prospects

        # Export to CSV
        job.progress = 95
        job.progress_message = "Generating output files..."

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_filename = f"healthcare_prospects_{timestamp}.csv"
        output_path = OUTPUT_DIR / output_filename

        df = prospector.to_dataframe()
        df.to_csv(output_path, index=False)
        job.output_file = output_filename

        if not df.empty and "Score" in df.columns:
            hot_df = df[df["Score"] >= 70]
            if not hot_df.empty:
                hot_filename = f"healthcare_prospects_{timestamp}_HOT.csv"
                hot_path = OUTPUT_DIR / hot_filename
                hot_df.to_csv(hot_path, index=False)
                job.hot_file = hot_filename

        if not df.empty:
            job.stats = prospector.get_summary()
        else:
            job.stats = {"total": 0, "message": "No prospects found"}

        job.progress = 100
        job.progress_message = "Complete!"
        job.status = "completed"
        job.completed_at = datetime.now()

    except Exception as e:
        job.status = "failed"
        job.error = str(e)
        job.completed_at = datetime.now()


def run_construction_job(job: ProspectorJob):
    """Run a construction prospect search job."""
    try:
        job.status = "running"
        job.started_at = datetime.now()
        job.progress_message = "Starting construction prospect search..."

        from prospector.industries.construction import ConstructionProspector

        config = {
            "target_states": job.config.get("states", ["FL"]),
            "limit_per_state": job.config.get("limit_per_state", 500),
        }

        prospector = ConstructionProspector(config)

        # Fetch with progress updates
        all_records = []
        states = config["target_states"]
        total_states = len(states)

        for i, state in enumerate(states):
            job.progress = int((i / total_states) * 80)
            job.progress_message = f"Fetching {state}... ({i+1}/{total_states})"

            state_records = prospector._fetch_state_data(state)
            all_records.extend(state_records)
            time.sleep(0.3)

        job.progress = 80
        job.progress_message = f"Processing {len(all_records)} records..."

        # Process records
        prospects = []
        for raw in all_records:
            try:
                record = prospector.parse_record(raw)
                record.source = prospector.get_industry_name()
                prospects.append(record)
            except Exception:
                continue

        # Score prospects
        job.progress = 90
        job.progress_message = "Scoring prospects..."

        from prospector.core.scoring import ScoringEngine
        scoring_engine = ScoringEngine(prospector.get_scoring_rules())
        prospects = [scoring_engine.score(r) for r in prospects]
        prospects.sort(key=lambda x: x.prospect_score, reverse=True)

        prospector._prospects = prospects

        # Export to CSV
        job.progress = 95
        job.progress_message = "Generating output files..."

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_filename = f"construction_prospects_{timestamp}.csv"
        output_path = OUTPUT_DIR / output_filename

        df = prospector.to_dataframe()
        df.to_csv(output_path, index=False)
        job.output_file = output_filename

        if not df.empty and "Score" in df.columns:
            hot_df = df[df["Score"] >= 70]
            if not hot_df.empty:
                hot_filename = f"construction_prospects_{timestamp}_HOT.csv"
                hot_path = OUTPUT_DIR / hot_filename
                hot_df.to_csv(hot_path, index=False)
                job.hot_file = hot_filename

        if not df.empty:
            job.stats = prospector.get_summary()
        else:
            job.stats = {"total": 0, "message": "No prospects found"}

        job.progress = 100
        job.progress_message = "Complete!"
        job.status = "completed"
        job.completed_at = datetime.now()

    except Exception as e:
        job.status = "failed"
        job.error = str(e)
        job.completed_at = datetime.now()


def run_aviation_job(job: ProspectorJob):
    """Run an aviation prospect search job."""
    try:
        job.status = "running"
        job.started_at = datetime.now()
        job.progress_message = "Starting aviation prospect search..."

        from prospector.industries.aviation import AviationProspector

        config = {
            "target_states": job.config.get("states", ["FL"]),
            "min_aircraft": job.config.get("min_aircraft", 1),
            "max_aircraft": job.config.get("max_aircraft", 100),
            "owner_types": job.config.get("owner_types", ["3", "7", "2"]),
            "limit_per_state": job.config.get("limit_per_state", 500),
        }

        if job.config.get("turbine_only"):
            config["engine_types"] = ["2", "3", "4", "5"]

        prospector = AviationProspector(config)

        job.progress = 10
        job.progress_message = "Downloading FAA aircraft database..."

        # Run the prospector
        prospects = prospector.run(score=True)

        job.progress = 95
        job.progress_message = "Generating output files..."

        # Export to CSV
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_filename = f"aviation_prospects_{timestamp}.csv"
        output_path = OUTPUT_DIR / output_filename

        df = prospector.to_dataframe()
        df.to_csv(output_path, index=False)
        job.output_file = output_filename

        if not df.empty and "Score" in df.columns:
            hot_df = df[df["Score"] >= 70]
            if not hot_df.empty:
                hot_filename = f"aviation_prospects_{timestamp}_HOT.csv"
                hot_path = OUTPUT_DIR / hot_filename
                hot_df.to_csv(hot_path, index=False)
                job.hot_file = hot_filename

        if not df.empty:
            job.stats = prospector.get_summary()
        else:
            job.stats = {"total": 0, "message": "No prospects found"}

        job.progress = 100
        job.progress_message = "Complete!"
        job.status = "completed"
        job.completed_at = datetime.now()

    except Exception as e:
        job.status = "failed"
        job.error = str(e)
        job.completed_at = datetime.now()


def run_federal_contractors_job(job: ProspectorJob):
    """Run a federal contractors prospect search job."""
    try:
        job.status = "running"
        job.started_at = datetime.now()
        job.progress_message = "Starting federal contractor search..."

        from prospector.industries.federal_contractors import FederalContractorProspector

        def progress_callback(progress, message):
            job.progress = progress
            job.progress_message = message

        prospector = FederalContractorProspector()

        prospects = prospector.search(
            states=job.config.get("states"),
            naics_codes=job.config.get("naics_codes"),
            small_business_only=job.config.get("small_business_only", True),
            active_only=job.config.get("active_only", True),
            limit=job.config.get("limit", 1000),
            progress_callback=progress_callback
        )

        job.progress = 90
        job.progress_message = "Generating output files..."

        # Export to CSV
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_filename = f"federal_contractors_{timestamp}.csv"
        output_path = OUTPUT_DIR / output_filename

        if prospects:
            import pandas as pd
            records = [p.to_dict() for p in prospects]
            df = pd.DataFrame(records)
            df.to_csv(output_path, index=False)
            job.output_file = output_filename

            # Calculate scores and create hot file
            avg_score = 50  # Default score
            hot_count = len([p for p in prospects if p.phone or p.email])
            
            job.stats = {
                "total": len(prospects),
                "hot_count": hot_count,
                "avg_score": avg_score
            }
        else:
            job.stats = {"total": 0, "message": "No prospects found"}

        job.progress = 100
        job.progress_message = "Complete!"
        job.status = "completed"
        job.completed_at = datetime.now()

    except Exception as e:
        job.status = "failed"
        job.error = str(e)
        job.completed_at = datetime.now()


def run_ppp_loans_job(job: ProspectorJob):
    """Run a PPP loan recipients prospect search job."""
    try:
        job.status = "running"
        job.started_at = datetime.now()
        job.progress_message = "Starting PPP loan recipient search..."

        from prospector.industries.ppp_loans import PPPLoanProspector

        def progress_callback(progress, message):
            job.progress = progress
            job.progress_message = message

        prospector = PPPLoanProspector()

        prospects = prospector.search(
            states=job.config.get("states"),
            min_loan_amount=job.config.get("min_loan_amount", 0),
            max_loan_amount=job.config.get("max_loan_amount", float('inf')),
            min_jobs=job.config.get("min_jobs", 0),
            forgiven_only=job.config.get("forgiven_only", False),
            limit=job.config.get("limit", 1000),
            progress_callback=progress_callback
        )

        job.progress = 90
        job.progress_message = "Generating output files..."

        # Export to CSV
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_filename = f"ppp_recipients_{timestamp}.csv"
        output_path = OUTPUT_DIR / output_filename

        if prospects:
            import pandas as pd
            records = [p.to_dict() for p in prospects]
            df = pd.DataFrame(records)
            df.to_csv(output_path, index=False)
            job.output_file = output_filename

            # Calculate stats
            total_loans = sum(p.raw_data.get('loan_amount', 0) for p in prospects)
            avg_loan = total_loans / len(prospects) if prospects else 0
            
            job.stats = {
                "total": len(prospects),
                "hot_count": len([p for p in prospects if p.raw_data.get('loan_amount', 0) >= 150000]),
                "avg_score": 50,
                "total_loan_amount": total_loans,
                "avg_loan_amount": round(avg_loan, 2)
            }
        else:
            job.stats = {"total": 0, "message": "No prospects found"}

        job.progress = 100
        job.progress_message = "Complete!"
        job.status = "completed"
        job.completed_at = datetime.now()

    except Exception as e:
        job.status = "failed"
        job.error = str(e)
        job.completed_at = datetime.now()


def run_ca_contractors_job(job: ProspectorJob):
    """Run a California contractors prospect search job."""
    try:
        job.status = "running"
        job.started_at = datetime.now()
        job.progress_message = "Starting California contractor search..."

        from prospector.industries.contractors_ca import CaliforniaContractorProspector

        def progress_callback(progress, message):
            job.progress = progress
            job.progress_message = message

        prospector = CaliforniaContractorProspector()

        prospects = prospector.search(
            license_types=job.config.get("license_types"),
            cities=job.config.get("cities"),
            active_only=job.config.get("active_only", True),
            has_workers_comp=job.config.get("has_workers_comp", False),
            limit=job.config.get("limit", 1000),
            progress_callback=progress_callback
        )

        job.progress = 90
        job.progress_message = "Generating output files..."

        # Export to CSV
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_filename = f"ca_contractors_{timestamp}.csv"
        output_path = OUTPUT_DIR / output_filename

        if prospects:
            import pandas as pd
            records = [p.to_dict() for p in prospects]
            df = pd.DataFrame(records)
            df.to_csv(output_path, index=False)
            job.output_file = output_filename

            job.stats = {
                "total": len(prospects),
                "hot_count": len([p for p in prospects if p.phone]),
                "avg_score": 50
            }
        else:
            job.stats = {"total": 0, "message": "No prospects found"}

        job.progress = 100
        job.progress_message = "Complete!"
        job.status = "completed"
        job.completed_at = datetime.now()

    except Exception as e:
        job.status = "failed"
        job.error = str(e)
        job.completed_at = datetime.now()


def run_restaurant_job(job: ProspectorJob):
    """Run a restaurant prospect search job."""
    try:
        job.status = "running"
        job.started_at = datetime.now()
        job.progress_message = "Starting restaurant search..."

        from prospector.industries.restaurants import RestaurantProspector

        def progress_callback(progress, message):
            job.progress = progress
            job.progress_message = message

        prospector = RestaurantProspector()

        prospects = prospector.search(
            boroughs=job.config.get("boroughs"),
            cuisines=job.config.get("cuisines"),
            grades=job.config.get("grades"),
            limit=job.config.get("limit", 1000),
            progress_callback=progress_callback
        )

        job.progress = 90
        job.progress_message = "Generating output files..."

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_filename = f"restaurants_{timestamp}.csv"
        output_path = OUTPUT_DIR / output_filename

        if prospects:
            import pandas as pd
            records = [p.to_dict() for p in prospects]
            df = pd.DataFrame(records)
            df.to_csv(output_path, index=False)
            job.output_file = output_filename

            hot_prospects = [p for p in prospects if p.phone]
            
            job.stats = {
                "total": len(prospects),
                "hot_count": len(hot_prospects),
                "avg_score": round(sum(p.prospect_score for p in prospects) / len(prospects)) if prospects else 0
            }
        else:
            job.stats = {"total": 0, "message": "No restaurants found"}

        job.progress = 100
        job.progress_message = "Complete!"
        job.status = "completed"
        job.completed_at = datetime.now()

    except Exception as e:
        job.status = "failed"
        job.error = str(e)
        job.completed_at = datetime.now()


def run_ct_licenses_job(job: ProspectorJob):
    """Run a Connecticut licensed businesses search job."""
    try:
        job.status = "running"
        job.started_at = datetime.now()
        job.progress_message = "Starting CT licensed businesses search..."

        from prospector.industries.ct_licenses import CTLicenseProspector

        def progress_callback(progress, message):
            job.progress = progress
            job.progress_message = message

        prospector = CTLicenseProspector()

        credential_types = job.config.get("credential_types")
        if credential_types:
            credential_types = [c.strip() for c in credential_types.split(",") if c.strip()]
        
        cities = job.config.get("cities")
        if cities:
            cities = [c.strip() for c in cities.split(",") if c.strip()]

        prospects = prospector.search(
            credential_types=credential_types if credential_types else None,
            cities=cities if cities else None,
            active_only=job.config.get("active_only", True),
            businesses_only=job.config.get("businesses_only", True),
            limit=job.config.get("limit", 1000),
            offset=job.config.get("offset", 0),
            progress_callback=progress_callback
        )

        job.progress = 90
        job.progress_message = "Generating output files..."

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_filename = f"ct_licenses_{timestamp}.csv"
        output_path = OUTPUT_DIR / output_filename

        if prospects:
            import pandas as pd
            records = [p.to_dict() for p in prospects]
            df = pd.DataFrame(records)
            df.to_csv(output_path, index=False)
            job.output_file = output_filename

            hot_prospects = [p for p in prospects if p.prospect_score >= 70]
            
            job.stats = {
                "total": len(prospects),
                "hot_count": len(hot_prospects),
                "avg_score": round(sum(p.prospect_score for p in prospects) / len(prospects)) if prospects else 0
            }
        else:
            job.stats = {"total": 0, "message": "No businesses found"}

        job.progress = 100
        job.progress_message = "Complete!"
        job.status = "completed"
        job.completed_at = datetime.now()

    except Exception as e:
        job.status = "failed"
        job.error = str(e)
        job.completed_at = datetime.now()


def run_wa_contractors_job(job: ProspectorJob):
    """Run a Washington State contractors search job."""
    try:
        job.status = "running"
        job.started_at = datetime.now()
        job.progress_message = "Starting WA contractors search..."

        from prospector.industries.wa_contractors import WAContractorProspector

        def progress_callback(progress, message):
            job.progress = progress
            job.progress_message = message

        prospector = WAContractorProspector()

        cities = job.config.get("cities")
        if cities:
            cities = [c.strip() for c in cities.split(",") if c.strip()]
        
        counties = job.config.get("counties")
        if counties:
            counties = [c.strip() for c in counties.split(",") if c.strip()]

        prospects = prospector.search(
            cities=cities if cities else None,
            counties=counties if counties else None,
            business_name=job.config.get("business_name"),
            active_only=job.config.get("active_only", True),
            limit=job.config.get("limit", 1000),
            offset=job.config.get("offset", 0),
            progress_callback=progress_callback
        )

        job.progress = 90
        job.progress_message = "Generating output files..."

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_filename = f"wa_contractors_{timestamp}.csv"
        output_path = OUTPUT_DIR / output_filename

        if prospects:
            import pandas as pd
            records = [p.to_dict() for p in prospects]
            df = pd.DataFrame(records)
            df.to_csv(output_path, index=False)
            job.output_file = output_filename

            with_phone = [p for p in prospects if p.phone]
            hot_prospects = [p for p in prospects if p.prospect_score >= 70]
            
            job.stats = {
                "total": len(prospects),
                "hot_count": len(hot_prospects),
                "with_phone": len(with_phone),
                "avg_score": round(sum(p.prospect_score for p in prospects) / len(prospects)) if prospects else 0
            }
        else:
            job.stats = {"total": 0, "message": "No contractors found"}

        job.progress = 100
        job.progress_message = "Complete!"
        job.status = "completed"
        job.completed_at = datetime.now()

    except Exception as e:
        job.status = "failed"
        job.error = str(e)
        job.completed_at = datetime.now()


def run_ct_ucc_job(job: ProspectorJob):
    """Run a Connecticut UCC filings prospect search job."""
    try:
        job.status = "running"
        job.started_at = datetime.now()

        from prospector.industries.ct_ucc import CTUCCProspector

        prospector = CTUCCProspector()

        def progress_callback(pct, msg):
            job.progress = pct
            job.progress_message = msg

        cities = None
        if job.config.get("cities"):
            cities = [c.strip() for c in job.config["cities"].split(",") if c.strip()]

        lien_types = None
        if job.config.get("lien_types"):
            lien_types = [t.strip() for t in job.config["lien_types"].split(",") if t.strip()]

        prospects = prospector.search(
            debtor_name=job.config.get("debtor_name") or None,
            secured_party=job.config.get("secured_party") or None,
            cities=cities,
            lien_types=lien_types,
            filed_after=job.config.get("filed_after") or None,
            active_only=job.config.get("active_only", True),
            limit=job.config.get("limit", 1000),
            progress_callback=progress_callback
        )

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_filename = f"ct_ucc_{timestamp}.csv"
        output_path = OUTPUT_DIR / output_filename

        if prospects:
            import pandas as pd
            records = [p.to_dict() for p in prospects]
            df = pd.DataFrame(records)
            df.to_csv(output_path, index=False)
            job.output_file = output_filename

            hot_prospects = [p for p in prospects if p.prospect_score >= 70]
            
            job.stats = {
                "total": len(prospects),
                "hot_count": len(hot_prospects),
                "with_phone": 0,
                "avg_score": round(sum(p.prospect_score for p in prospects) / len(prospects)) if prospects else 0
            }
        else:
            job.stats = {"total": 0, "message": "No UCC filings found"}

        job.progress = 100
        job.progress_message = "Complete!"
        job.status = "completed"
        job.completed_at = datetime.now()

    except Exception as e:
        job.status = "failed"
        job.error = str(e)
        job.completed_at = datetime.now()


def run_or_ucc_job(job: ProspectorJob):
    """Run an Oregon UCC filings prospect search job."""
    try:
        job.status = "running"
        job.started_at = datetime.now()

        from prospector.industries.or_ucc import ORUCCProspector

        prospector = ORUCCProspector()

        def progress_callback(pct, msg):
            job.progress = pct
            job.progress_message = msg

        prospects = prospector.search(
            debtor_name=job.config.get("debtor_name") or None,
            secured_party=job.config.get("secured_party") or None,
            filed_after=job.config.get("filed_after") or None,
            limit=job.config.get("limit", 1000),
            offset=job.config.get("offset", 0),
            progress_callback=progress_callback
        )

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_filename = f"or_ucc_{timestamp}.csv"
        output_path = OUTPUT_DIR / output_filename

        if prospects:
            import pandas as pd
            records = [p.to_dict() for p in prospects]
            df = pd.DataFrame(records)
            df.to_csv(output_path, index=False)
            job.output_file = output_filename

            hot_prospects = [p for p in prospects if p.prospect_score >= 70]
            
            job.stats = {
                "total": len(prospects),
                "hot_count": len(hot_prospects),
                "with_phone": 0,
                "avg_score": round(sum(p.prospect_score for p in prospects) / len(prospects)) if prospects else 0
            }
        else:
            job.stats = {"total": 0, "message": "No UCC filings found"}

        job.progress = 100
        job.progress_message = "Complete!"
        job.status = "completed"
        job.completed_at = datetime.now()

    except Exception as e:
        job.status = "failed"
        job.error = str(e)
        job.completed_at = datetime.now()


def run_co_ucc_job(job: ProspectorJob):
    """Run a Colorado UCC filings prospect search job."""
    try:
        job.status = "running"
        job.started_at = datetime.now()

        from prospector.industries.co_ucc import COUCCProspector

        prospector = COUCCProspector()

        def progress_callback(pct, msg):
            job.progress = pct
            job.progress_message = msg

        prospects = prospector.search(
            debtor_name=job.config.get("debtor_name") or None,
            filing_type=job.config.get("filing_type") or None,
            filed_after=job.config.get("filed_after") or None,
            limit=job.config.get("limit", 1000),
            offset=job.config.get("offset", 0),
            progress_callback=progress_callback
        )

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_filename = f"co_ucc_{timestamp}.csv"
        output_path = OUTPUT_DIR / output_filename

        if prospects:
            import pandas as pd
            records = [p.to_dict() for p in prospects]
            df = pd.DataFrame(records)
            df.to_csv(output_path, index=False)
            job.output_file = output_filename

            hot_prospects = [p for p in prospects if p.prospect_score >= 70]
            
            job.stats = {
                "total": len(prospects),
                "hot_count": len(hot_prospects),
                "with_phone": 0,
                "avg_score": round(sum(p.prospect_score for p in prospects) / len(prospects)) if prospects else 0
            }
        else:
            job.stats = {"total": 0, "message": "No UCC filings found"}

        job.progress = 100
        job.progress_message = "Complete!"
        job.status = "completed"
        job.completed_at = datetime.now()

    except Exception as e:
        job.status = "failed"
        job.error = str(e)
        job.completed_at = datetime.now()


def run_npi_lookup_job(job: ProspectorJob):
    """Run an NPI lookup job."""
    try:
        job.status = "running"
        job.started_at = datetime.now()
        job.progress_message = "Looking up provider..."

        from prospector.industries.healthcare import lookup_by_npi

        npi_number = job.config.get("npi_number")
        result = lookup_by_npi(npi_number)

        if result:
            job.result = result
            job.status = "completed"
            job.progress = 100
            job.progress_message = "Found!"
        else:
            job.status = "completed"
            job.progress = 100
            job.progress_message = "No provider found"
            job.result = None

        job.completed_at = datetime.now()

    except Exception as e:
        job.status = "failed"
        job.error = str(e)
        job.completed_at = datetime.now()


# Routes

@app.route("/")
def index():
    """Main page."""
    return render_template("index.html")


@app.route("/api/prospect", methods=["POST"])
def start_prospect_search():
    """Start a new prospect search job."""
    data = request.json or {}

    # Parse states
    states_str = data.get("states", "FL")
    states = [s.strip().upper() for s in states_str.split(",") if s.strip()]

    if not states:
        return jsonify({"error": "Please provide at least one state"}), 400

    job_id = str(uuid.uuid4())
    job = ProspectorJob(job_id, {
        "states": states,
        "min_trucks": int(data.get("min_trucks", 1)),
        "max_trucks": int(data.get("max_trucks", 50)),
        "max_records": int(data.get("max_records", 5000)),
    })

    jobs[job_id] = job

    # Start background thread
    thread = threading.Thread(target=run_prospector_job, args=(job,))
    thread.daemon = True
    thread.start()

    return jsonify({"job_id": job_id})


@app.route("/api/lookup", methods=["POST"])
def start_lookup():
    """Start a DOT lookup."""
    data = request.json or {}
    dot_number = data.get("dot_number", "").strip()

    if not dot_number:
        return jsonify({"error": "Please provide a DOT number"}), 400

    job_id = str(uuid.uuid4())
    job = ProspectorJob(job_id, {"dot_number": dot_number})
    jobs[job_id] = job

    thread = threading.Thread(target=run_lookup_job, args=(job,))
    thread.daemon = True
    thread.start()

    return jsonify({"job_id": job_id})


@app.route("/api/search", methods=["POST"])
def start_search():
    """Start a name search."""
    data = request.json or {}
    company_name = data.get("company_name", "").strip()

    if not company_name:
        return jsonify({"error": "Please provide a company name"}), 400

    job_id = str(uuid.uuid4())
    job = ProspectorJob(job_id, {
        "company_name": company_name,
        "state": data.get("state", "").strip().upper() or None,
        "limit": int(data.get("limit", 25)),
    })
    jobs[job_id] = job

    thread = threading.Thread(target=run_search_job, args=(job,))
    thread.daemon = True
    thread.start()

    return jsonify({"job_id": job_id})


@app.route("/api/city", methods=["POST"])
def start_city_search():
    """Start a city-based search."""
    data = request.json or {}
    city = data.get("city", "").strip()
    state = data.get("state", "").strip().upper()

    if not city or not state:
        return jsonify({"error": "Please provide both city and state"}), 400

    job_id = str(uuid.uuid4())
    job = ProspectorJob(job_id, {
        "city": city,
        "state": state,
        "min_trucks": int(data.get("min_trucks", 1)),
        "max_trucks": int(data.get("max_trucks", 50)),
    })
    jobs[job_id] = job

    thread = threading.Thread(target=run_city_job, args=(job,))
    thread.daemon = True
    thread.start()

    return jsonify({"job_id": job_id})


@app.route("/api/healthcare", methods=["POST"])
def start_healthcare_search():
    """Start a new healthcare prospect search job."""
    data = request.json or {}

    states_str = data.get("states", "FL")
    states = [s.strip().upper() for s in states_str.split(",") if s.strip()]

    if not states:
        return jsonify({"error": "Please provide at least one state"}), 400

    job_id = str(uuid.uuid4())
    job = ProspectorJob(job_id, {
        "states": states,
        "organizations_only": data.get("organizations_only", True),
        "limit_per_state": int(data.get("limit_per_state", 500)),
    })

    jobs[job_id] = job

    thread = threading.Thread(target=run_healthcare_job, args=(job,))
    thread.daemon = True
    thread.start()

    return jsonify({"job_id": job_id})


@app.route("/api/construction", methods=["POST"])
def start_construction_search():
    """Start a new construction prospect search job."""
    data = request.json or {}

    states_str = data.get("states", "FL")
    states = [s.strip().upper() for s in states_str.split(",") if s.strip()]

    if not states:
        return jsonify({"error": "Please provide at least one state"}), 400

    job_id = str(uuid.uuid4())
    job = ProspectorJob(job_id, {
        "states": states,
        "limit_per_state": int(data.get("limit_per_state", 500)),
    })

    jobs[job_id] = job

    thread = threading.Thread(target=run_construction_job, args=(job,))
    thread.daemon = True
    thread.start()

    return jsonify({"job_id": job_id})


@app.route("/api/aviation", methods=["POST"])
def start_aviation_search():
    """Start a new aviation prospect search job."""
    data = request.json or {}

    states_str = data.get("states", "FL")
    states = [s.strip().upper() for s in states_str.split(",") if s.strip()]

    if not states:
        return jsonify({"error": "Please provide at least one state"}), 400

    job_id = str(uuid.uuid4())
    job = ProspectorJob(job_id, {
        "states": states,
        "min_aircraft": int(data.get("min_aircraft", 1)),
        "max_aircraft": int(data.get("max_aircraft", 100)),
        "businesses_only": data.get("businesses_only", True),
        "owner_types": ["3", "7", "2"] if data.get("businesses_only", True) else ["1", "2", "3", "4", "7"],
        "turbine_only": data.get("turbine_only", False),
        "limit_per_state": int(data.get("limit_per_state", 500)),
    })

    jobs[job_id] = job

    thread = threading.Thread(target=run_aviation_job, args=(job,))
    thread.daemon = True
    thread.start()

    return jsonify({"job_id": job_id})


@app.route("/api/federal-contractors", methods=["POST"])
def start_federal_contractors_search():
    """Start a new federal contractors prospect search job."""
    data = request.json or {}

    states_str = data.get("states", "")
    states = [s.strip().upper() for s in states_str.split(",") if s.strip()] if states_str else None

    job_id = str(uuid.uuid4())
    job = ProspectorJob(job_id, {
        "states": states,
        "naics_codes": data.get("naics_codes", "").split(",") if data.get("naics_codes") else None,
        "small_business_only": data.get("small_business_only", True),
        "active_only": data.get("active_only", True),
        "limit": int(data.get("limit", 1000)),
    })

    jobs[job_id] = job

    thread = threading.Thread(target=run_federal_contractors_job, args=(job,))
    thread.daemon = True
    thread.start()

    return jsonify({"job_id": job_id})


@app.route("/api/ppp-loans", methods=["POST"])
def start_ppp_loans_search():
    """Start a new PPP loan recipients prospect search job."""
    data = request.json or {}

    states_str = data.get("states", "")
    states = [s.strip().upper() for s in states_str.split(",") if s.strip()] if states_str else None

    job_id = str(uuid.uuid4())
    job = ProspectorJob(job_id, {
        "states": states,
        "min_loan_amount": float(data.get("min_loan_amount", 0)),
        "max_loan_amount": float(data.get("max_loan_amount", 10000000)),
        "min_jobs": int(data.get("min_jobs", 0)),
        "forgiven_only": data.get("forgiven_only", False),
        "limit": int(data.get("limit", 1000)),
    })

    jobs[job_id] = job

    thread = threading.Thread(target=run_ppp_loans_job, args=(job,))
    thread.daemon = True
    thread.start()

    return jsonify({"job_id": job_id})


@app.route("/api/ca-contractors", methods=["POST"])
def start_ca_contractors_search():
    """Start a new California contractors prospect search job."""
    data = request.json or {}

    license_types_str = data.get("license_types", "")
    license_types = [lt.strip() for lt in license_types_str.split(",") if lt.strip()] if license_types_str else None

    cities_str = data.get("cities", "")
    cities = [c.strip() for c in cities_str.split(",") if c.strip()] if cities_str else None

    job_id = str(uuid.uuid4())
    job = ProspectorJob(job_id, {
        "license_types": license_types,
        "cities": cities,
        "active_only": data.get("active_only", True),
        "has_workers_comp": data.get("has_workers_comp", False),
        "limit": int(data.get("limit", 1000)),
    })

    jobs[job_id] = job

    thread = threading.Thread(target=run_ca_contractors_job, args=(job,))
    thread.daemon = True
    thread.start()

    return jsonify({"job_id": job_id})


@app.route("/api/restaurants", methods=["POST"])
def start_restaurant_search():
    """Start a new restaurant prospect search job."""
    data = request.json or {}

    boroughs_str = data.get("boroughs", "")
    boroughs = [b.strip().upper() for b in boroughs_str.split(",") if b.strip()] if boroughs_str else None

    cuisines_str = data.get("cuisines", "")
    cuisines = [c.strip() for c in cuisines_str.split(",") if c.strip()] if cuisines_str else None

    grades_str = data.get("grades", "")
    grades = [g.strip().upper() for g in grades_str.split(",") if g.strip()] if grades_str else None

    job_id = str(uuid.uuid4())
    job = ProspectorJob(job_id, {
        "boroughs": boroughs,
        "cuisines": cuisines,
        "grades": grades,
        "limit": int(data.get("limit", 1000)),
    })

    jobs[job_id] = job

    thread = threading.Thread(target=run_restaurant_job, args=(job,))
    thread.daemon = True
    thread.start()

    return jsonify({"job_id": job_id})


@app.route("/api/ct-licenses", methods=["POST"])
def start_ct_licenses_search():
    """Start a new Connecticut licensed businesses prospect search job."""
    data = request.json or {}

    credential_types = data.get("credential_types", "")
    cities = data.get("cities", "")

    job_id = str(uuid.uuid4())
    job = ProspectorJob(job_id, {
        "credential_types": credential_types,
        "cities": cities,
        "active_only": data.get("active_only", True),
        "businesses_only": data.get("businesses_only", True),
        "limit": int(data.get("limit", 1000)),
        "offset": int(data.get("offset", 0)),
    })

    jobs[job_id] = job

    thread = threading.Thread(target=run_ct_licenses_job, args=(job,))
    thread.daemon = True
    thread.start()

    return jsonify({"job_id": job_id})


@app.route("/api/wa-contractors", methods=["POST"])
def start_wa_contractors_search():
    """Start a new Washington State contractors prospect search job."""
    data = request.json or {}

    job_id = str(uuid.uuid4())
    job = ProspectorJob(job_id, {
        "cities": data.get("cities", ""),
        "counties": data.get("counties", ""),
        "business_name": data.get("business_name", ""),
        "active_only": data.get("active_only", True),
        "limit": int(data.get("limit", 1000)),
        "offset": int(data.get("offset", 0)),
    })

    jobs[job_id] = job

    thread = threading.Thread(target=run_wa_contractors_job, args=(job,))
    thread.daemon = True
    thread.start()

    return jsonify({"job_id": job_id})


@app.route("/api/ct-ucc", methods=["POST"])
def start_ct_ucc_search():
    """Start a new Connecticut UCC filings prospect search job."""
    data = request.json or {}

    job_id = str(uuid.uuid4())
    job = ProspectorJob(job_id, {
        "debtor_name": data.get("debtor_name", ""),
        "secured_party": data.get("secured_party", ""),
        "cities": data.get("cities", ""),
        "lien_types": data.get("lien_types", ""),
        "filed_after": data.get("filed_after", ""),
        "active_only": data.get("active_only", True),
        "limit": int(data.get("limit", 1000)),
    })

    jobs[job_id] = job

    thread = threading.Thread(target=run_ct_ucc_job, args=(job,))
    thread.daemon = True
    thread.start()

    return jsonify({"job_id": job_id})


@app.route("/api/or-ucc", methods=["POST"])
def start_or_ucc_search():
    """Start a new Oregon UCC filings prospect search job."""
    data = request.json or {}

    job_id = str(uuid.uuid4())
    job = ProspectorJob(job_id, {
        "debtor_name": data.get("debtor_name", ""),
        "secured_party": data.get("secured_party", ""),
        "filed_after": data.get("filed_after", ""),
        "limit": int(data.get("limit", 1000)),
        "offset": int(data.get("offset", 0)),
    })

    jobs[job_id] = job

    thread = threading.Thread(target=run_or_ucc_job, args=(job,))
    thread.daemon = True
    thread.start()

    return jsonify({"job_id": job_id})


@app.route("/api/co-ucc", methods=["POST"])
def start_co_ucc_search():
    """Start a new Colorado UCC filings prospect search job."""
    data = request.json or {}

    job_id = str(uuid.uuid4())
    job = ProspectorJob(job_id, {
        "debtor_name": data.get("debtor_name", ""),
        "filing_type": data.get("filing_type", ""),
        "filed_after": data.get("filed_after", ""),
        "limit": int(data.get("limit", 1000)),
        "offset": int(data.get("offset", 0)),
    })

    jobs[job_id] = job

    thread = threading.Thread(target=run_co_ucc_job, args=(job,))
    thread.daemon = True
    thread.start()

    return jsonify({"job_id": job_id})


@app.route("/api/npi-lookup", methods=["POST"])
def start_npi_lookup():
    """Start an NPI lookup."""
    data = request.json or {}
    npi_number = data.get("npi_number", "").strip()

    if not npi_number:
        return jsonify({"error": "Please provide an NPI number"}), 400

    job_id = str(uuid.uuid4())
    job = ProspectorJob(job_id, {"npi_number": npi_number})
    jobs[job_id] = job

    thread = threading.Thread(target=run_npi_lookup_job, args=(job,))
    thread.daemon = True
    thread.start()

    return jsonify({"job_id": job_id})


@app.route("/api/job/<job_id>")
def get_job_status(job_id):
    """Get job status."""
    job = jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404

    response = job.to_dict()

    # Include result for completed lookup/search jobs
    if job.status == "completed" and job.result is not None:
        response["result"] = job.result

    return jsonify(response)


@app.route("/api/download/<filename>")
def download_file(filename):
    """Download an output file."""
    # Security: ensure filename is safe
    safe_filename = Path(filename).name
    filepath = OUTPUT_DIR / safe_filename

    if not filepath.exists():
        return jsonify({"error": "File not found"}), 404

    return send_file(
        filepath,
        as_attachment=True,
        download_name=safe_filename,
        mimetype="text/csv",
    )


@app.route("/api/files")
def list_files():
    """List available output files."""
    files = []
    for f in OUTPUT_DIR.glob("*.csv"):
        stat = f.stat()
        files.append({
            "name": f.name,
            "size": stat.st_size,
            "created": datetime.fromtimestamp(stat.st_mtime).isoformat(),
        })
    files.sort(key=lambda x: x["created"], reverse=True)
    return jsonify(files)


@app.route("/api/match", methods=["POST"])
def match_data():
    """Match uploaded file against prospect data."""
    import pandas as pd
    from difflib import SequenceMatcher

    if 'file' not in request.files:
        return jsonify({"error": "No file uploaded"}), 400

    file = request.files['file']
    name_column = request.form.get('name_column', '')
    match_threshold = float(request.form.get('threshold', 0.8))
    prospect_source = request.form.get('prospect_source', 'existing')

    if file.filename == '':
        return jsonify({"error": "No file selected"}), 400

    try:
        if file.filename.endswith('.xlsx') or file.filename.endswith('.xls'):
            uploaded_df = pd.read_excel(file)
        else:
            uploaded_df = pd.read_csv(file)

        # Handle prospect file - either from existing files or uploaded
        if prospect_source == 'upload':
            if 'prospect_upload' not in request.files:
                return jsonify({"error": "No prospect file uploaded"}), 400
            prospect_file_obj = request.files['prospect_upload']
            if prospect_file_obj.filename == '':
                return jsonify({"error": "No prospect file selected"}), 400
            
            if prospect_file_obj.filename.endswith('.xlsx') or prospect_file_obj.filename.endswith('.xls'):
                prospect_df = pd.read_excel(prospect_file_obj)
            else:
                prospect_df = pd.read_csv(prospect_file_obj)
            
            # Use provided column name for uploaded prospect file
            prospect_name_column = request.form.get('prospect_name_column', '')
            if prospect_name_column and prospect_name_column in prospect_df.columns:
                prospect_name_col = prospect_name_column
            else:
                # Try to find a name column
                possible_cols = [c for c in prospect_df.columns if 'name' in c.lower() or 'company' in c.lower() or 'business' in c.lower()]
                prospect_name_col = possible_cols[0] if possible_cols else prospect_df.columns[0]
        else:
            prospect_file = request.form.get('prospect_file', '')
            if not prospect_file:
                return jsonify({"error": "No prospect file selected"}), 400

            safe_prospect_file = Path(prospect_file).name
            prospect_path = OUTPUT_DIR / safe_prospect_file
            if not prospect_path.exists():
                return jsonify({"error": "Prospect file not found"}), 404
            
            prospect_df = pd.read_csv(prospect_path)
            prospect_name_col = 'Company Name' if 'Company Name' in prospect_df.columns else prospect_df.columns[0]

        if not name_column or name_column not in uploaded_df.columns:
            possible_cols = [c for c in uploaded_df.columns if 'name' in c.lower() or 'company' in c.lower() or 'business' in c.lower()]
            if possible_cols:
                name_column = possible_cols[0]
            else:
                name_column = uploaded_df.columns[0]

        def normalize_name(name):
            if pd.isna(name):
                return ""
            name = str(name).upper().strip()
            for suffix in [' LLC', ' INC', ' CORP', ' CO', ' LTD', ' LP', ' L.L.C.', ' L.L.C', ' INC.', ' CORPORATION', ' COMPANY', ' TRUCKING', ' TRANSPORT', ' LOGISTICS', ' FREIGHT', ' SERVICES']:
                name = name.replace(suffix, '')
            return ' '.join(name.split())

        def match_score(name1, name2):
            n1, n2 = normalize_name(name1), normalize_name(name2)
            if not n1 or not n2:
                return 0.0
            return SequenceMatcher(None, n1, n2).ratio()

        prospect_df['_normalized_name'] = prospect_df[prospect_name_col].apply(normalize_name)
        prospect_records = prospect_df.to_dict('records')
        
        normalized_lookup = {}
        for i, rec in enumerate(prospect_records):
            norm = rec['_normalized_name']
            if norm:
                first_word = norm.split()[0] if norm.split() else ''
                if first_word not in normalized_lookup:
                    normalized_lookup[first_word] = []
                normalized_lookup[first_word].append((i, norm, rec))

        matches = []
        unmatched = []

        for idx, row in uploaded_df.iterrows():
            uploaded_name = row[name_column]
            uploaded_norm = normalize_name(uploaded_name)
            if not uploaded_norm:
                unmatched.append(row.to_dict())
                continue
                
            best_match = None
            best_score = 0
            
            first_word = uploaded_norm.split()[0] if uploaded_norm.split() else ''
            candidates = normalized_lookup.get(first_word, [])
            
            if not candidates:
                for key in normalized_lookup:
                    candidates.extend(normalized_lookup[key][:50])
                candidates = candidates[:200]
            
            for pidx, pnorm, prec in candidates:
                score = SequenceMatcher(None, uploaded_norm, pnorm).ratio()
                if score > best_score:
                    best_score = score
                    best_match = prec

            if best_score >= match_threshold and best_match is not None:
                match_record = row.to_dict()
                for col in prospect_df.columns:
                    if col != '_normalized_name':
                        match_record[f"PROSPECT_{col}"] = best_match[col]
                match_record['MATCH_SCORE'] = round(best_score * 100, 1)
                matches.append(match_record)
            else:
                unmatched.append(row.to_dict())

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        matched_filename = f"matched_data_{timestamp}.csv"
        matched_path = OUTPUT_DIR / matched_filename

        if matches:
            matched_df = pd.DataFrame(matches)
            matched_df.to_csv(matched_path, index=False)

        return jsonify({
            "success": True,
            "matched_count": len(matches),
            "unmatched_count": len(unmatched),
            "total_uploaded": len(uploaded_df),
            "total_prospects": len(prospect_df),
            "output_file": matched_filename if matches else None,
            "name_column_used": name_column,
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/file-columns", methods=["POST"])
def get_file_columns():
    """Get column names from uploaded file for preview."""
    import pandas as pd

    if 'file' not in request.files:
        return jsonify({"error": "No file uploaded"}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "No file selected"}), 400

    try:
        if file.filename.endswith('.xlsx') or file.filename.endswith('.xls'):
            df = pd.read_excel(file, nrows=5)
        else:
            df = pd.read_csv(file, nrows=5)

        name_cols = [c for c in df.columns if 'name' in c.lower() or 'company' in c.lower() or 'business' in c.lower()]
        suggested = name_cols[0] if name_cols else df.columns[0]

        return jsonify({
            "columns": list(df.columns),
            "suggested_name_column": suggested,
            "row_count": len(df),
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/health")
def health_check():
    """Health check endpoint."""
    return jsonify({"status": "healthy", "timestamp": datetime.now().isoformat()})


# Error handlers

@app.errorhandler(404)
def not_found(e):
    return jsonify({"error": "Not found"}), 404


@app.errorhandler(500)
def server_error(e):
    return jsonify({"error": "Internal server error"}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_ENV") == "development"
    app.run(host="0.0.0.0", port=port, debug=debug)
