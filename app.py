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
