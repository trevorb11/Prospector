# Prospector - MCA Lead Finder

## Overview

Prospector is a lead generation and scoring tool designed for merchant cash advance (MCA), equipment financing, and business loan providers. It finds and evaluates business prospects across multiple industries using public data sources. The primary use case is the trucking industry via FMCSA data, with extensibility built in for healthcare, aviation, and construction industries.

The application provides three interfaces: a web UI (Flask-based), a CLI (Click-based), and programmatic API access. It's optimized for deployment on Replit.

## User Preferences

Preferred communication style: Simple, everyday language.

## System Architecture

### Application Structure

The codebase follows a modular architecture with clear separation of concerns:

- **Core Framework** (`prospector/core/`): Abstract base classes and shared logic
  - `base.py`: `ProspectRecord` dataclass and `IndustryProspector` abstract base class
  - `scoring.py`: Configurable scoring engine with rule-based evaluation
  - `enricher.py`: Lead enrichment for matching existing lists against data sources

- **Industry Modules** (`prospector/industries/`): Industry-specific implementations
  - Each industry inherits from `IndustryProspector`
  - Trucking is fully implemented using FMCSA/Socrata API
  - Healthcare, aviation, and construction have placeholder implementations

- **Exporters** (`prospector/exporters/`): Output format handlers
  - CSV and Excel export with automatic "hot prospects" filtering
  - Score-based sorting and multi-sheet Excel output

- **Web Interface** (`app.py` + `templates/`): Flask application for browser-based access
  - Background job processing for long-running searches
  - File downloads from the `output/` directory

- **CLI** (`prospector/cli.py`): Click-based command-line interface
  - Entry point via `main.py`

### Design Patterns

**Strategy Pattern**: Industry prospectors implement a common interface, allowing the scoring and export logic to work with any industry's data.

**Dataclass-based Records**: `ProspectRecord` provides a standardized structure across all industries, normalizing fields like company name, address, phone, and business metrics.

**Configurable Scoring**: The scoring engine uses rule objects (`ScoringRule`) with different types (range, presence, equals, contains, custom) to evaluate prospects. Base scores and rules are customizable per industry or use case.

### Data Flow

1. Industry prospector fetches raw data from external API (e.g., FMCSA/Socrata)
2. Raw records are parsed into `ProspectRecord` objects
3. Scoring engine evaluates each record against configured rules
4. Exporters output results to CSV/Excel files
5. Web UI or CLI presents results to user

### Background Jobs

The Flask app uses a simple in-memory job store with threading for background processing. Jobs track status, progress percentage, and completion state. This approach works for Replit's single-instance deployment model.

## External Dependencies

### APIs and Data Sources

- **FMCSA/DOT Open Data Portal** (`data.transportation.gov`): Primary data source for trucking prospects. Uses Socrata Open Data API (SODA). No authentication required for basic access; optional `SOCRATA_APP_TOKEN` environment variable enables higher rate limits.

- **CMS NPI Registry** (healthcare module): Free API, no authentication required. Placeholder implementation.

- **FAA Aircraft Registry** (aviation module): Downloadable CSV files from FAA. Placeholder implementation.

- **State Contractor Databases** (construction module): Varies by state, most require web scraping. Placeholder implementation.

### Python Dependencies

- **Web**: Flask, Gunicorn
- **CLI**: Click, Rich (terminal formatting)
- **Data Processing**: Pandas, OpenPyXL (Excel support)
- **HTTP**: Requests
- **Configuration**: python-dotenv, Pydantic

### File Storage

Output files are written to the `output/` directory. This directory is created automatically and persists across restarts on Replit.

### Environment Variables

- `SOCRATA_APP_TOKEN`: Optional token for higher FMCSA API rate limits
- `SECRET_KEY`: Flask session key (defaults to a placeholder value)