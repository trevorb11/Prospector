# Prospector

**Industry Lead Finder for MCA/Business Financing**

Prospector is a flexible, extensible tool for finding and scoring business prospects across multiple industries. Built for merchant cash advance, equipment financing, and business loan providers.

## Features

- **Multi-Industry Support**: Extensible framework that can be adapted for different industries
- **Trucking Industry**: Full FMCSA integration pulling from DOT public data
- **Smart Scoring**: Configurable scoring engine to rank prospects by fit
- **Lead Enrichment**: Enhance existing lead lists with official data
- **Multiple Exports**: CSV and Excel output with automatic "hot prospects" files
- **CLI & API**: Use from command line or integrate into your workflows

## Quick Start

### Installation

```bash
# Clone the repository
git clone <repo-url>
cd Prospector

# Install dependencies
pip install -r requirements.txt
```

### Basic Usage

```bash
# Find trucking prospects in default states
python main.py trucking

# Search specific states with fleet size filter
python main.py trucking -s FL,GA,TX -m 5 -M 25

# Look up a specific company by DOT number
python main.py lookup 1234567

# Search for companies by name
python main.py search "ABC Trucking" -s FL

# Get all carriers in a specific city
python main.py city Miami FL -m 3 -M 25

# Enrich an existing lead list
python main.py enrich my_leads.csv -o enriched_leads.csv
```

## Commands

### `trucking` - Find Trucking Prospects

Pull motor carrier data from the FMCSA database:

```bash
python main.py trucking [OPTIONS]

Options:
  -s, --states TEXT        Comma-separated state abbreviations (default: FL,GA,TX,CA,IL,NC,TN,OH,PA,NJ,NY)
  -m, --min-trucks INT     Minimum fleet size (default: 1)
  -M, --max-trucks INT     Maximum fleet size (default: 50)
  -o, --output PATH        Output file path
  -f, --format [csv|excel] Output format (default: csv)
  --hot-threshold INT      Score threshold for hot prospects (default: 70)
  --app-token TEXT         Socrata API token for higher rate limits
```

### `enrich` - Enrich Existing Leads

Add FMCSA data to your existing lead list:

```bash
python main.py enrich INPUT_FILE [OPTIONS]

Options:
  -o, --output PATH       Output file path
  --dot-column TEXT       Column name for DOT number (auto-detected)
  --name-column TEXT      Column name for company name (auto-detected)
  --state-column TEXT     Column name for state (auto-detected)
```

### `lookup` - Company Lookup

Look up a specific company by DOT number:

```bash
python main.py lookup 1234567
```

### `search` - Name Search

Search for companies by name:

```bash
python main.py search "ABC Trucking" -s FL -l 20
```

### `city` - City-Based Search

Get all carriers in a specific city (great for local campaigns):

```bash
python main.py city Miami FL -m 3 -M 25 -o miami_carriers.csv
```

## Scoring System

Prospects are scored 0-100 based on fit for equipment financing:

| Component | Points | Description |
|-----------|--------|-------------|
| Base Score | 50 | All prospects start here |
| Fleet 5-20 trucks | +30 | Sweet spot for financing deals |
| Fleet 2-4 trucks | +20 | Small but established |
| Fleet 21-35 trucks | +15 | Medium fleet |
| Fleet 1 truck | +5 | Owner-operator |
| Has Phone | +10 | Contact info available |
| Has MC Authority | +10 | For-hire carrier indicator |

### Score Interpretation

| Score | Priority | Recommended Action |
|-------|----------|-------------------|
| 70+ (HOT) | High | Phone call first |
| 50-69 | Medium | Email sequence |
| <50 | Lower | Nurture sequence |

## Output Files

The tool generates:

1. **All Prospects** (`trucking_prospects_YYYYMMDD.csv`) - Complete list sorted by score
2. **Hot Prospects** (`trucking_prospects_YYYYMMDD_HOT.csv`) - Score 70+ only

Excel exports include additional sheets:
- All Prospects
- Hot Prospects (70+)
- Medium (50-69)
- Summary statistics

## Data Fields

| Field | Description |
|-------|-------------|
| Score | Prospect quality score (higher = better fit) |
| Company Name | Legal business name |
| DBA Name | "Doing Business As" name |
| Phone | Business phone (formatted) |
| Address/City/State/ZIP | Physical business location |
| DOT Number | Unique USDOT identifier |
| MC Number | Motor Carrier authority number |
| Trucks | Number of power units |
| Drivers | Number of registered drivers |

## Extending to Other Industries

The framework is designed for extensibility. To add a new industry:

1. Create a new file in `prospector/industries/`
2. Inherit from `IndustryProspector`
3. Implement required methods:
   - `get_industry_name()`
   - `fetch_prospects()`
   - `parse_record()`
4. Optionally override `get_scoring_rules()` for custom scoring

Example skeleton:

```python
from prospector.core.base import IndustryProspector, ProspectRecord

class ConstructionProspector(IndustryProspector):
    def get_industry_name(self) -> str:
        return "Construction"

    def fetch_prospects(self):
        # Fetch from your data source
        pass

    def parse_record(self, raw_record):
        # Convert to ProspectRecord
        pass
```

## Configuration

Copy `config/default.yaml` to `config/local.yaml` and customize:

```yaml
trucking:
  target_states:
    - FL
    - GA
    - TX
  min_power_units: 5
  max_power_units: 25

scoring:
  hot_threshold: 70
```

## API Rate Limits

The FMCSA data uses the Socrata API:
- **Without token**: ~1,000 requests/hour
- **With token**: Much higher limits

Get a free app token at https://data.transportation.gov and set it:

```bash
export SOCRATA_APP_TOKEN=your_token_here
python main.py trucking
```

Or pass directly:
```bash
python main.py trucking --app-token your_token_here
```

## Importing to CRM (GoHighLevel)

1. Export prospects to CSV
2. In GHL: Contacts → Import
3. Map fields:
   - Company Name → Company
   - Phone → Phone
   - Address fields → Address
   - Score → Custom field "Prospect Score"
   - DOT Number → Custom field
   - Trucks → Custom field for segmentation
4. Tag imported contacts (e.g., "FMCSA Import - Jan 2025")
5. Add to appropriate pipeline/workflow

## Data Source & Compliance

- **Source**: DOT Open Data Portal (data.transportation.gov)
- **Dataset**: FMCSA Company Census File
- **License**: Public domain (US Government data)
- **Compliance**: This is publicly available business registration data. Standard CAN-SPAM and TCPA rules apply to outreach.

## Project Structure

```
Prospector/
├── main.py                 # Entry point
├── requirements.txt        # Dependencies
├── config/
│   └── default.yaml        # Default configuration
├── prospector/
│   ├── __init__.py
│   ├── cli.py              # Command-line interface
│   ├── core/
│   │   ├── base.py         # Base classes
│   │   ├── scoring.py      # Scoring engine
│   │   └── enricher.py     # Lead enrichment
│   ├── industries/
│   │   ├── __init__.py
│   │   └── trucking.py     # FMCSA implementation
│   └── utils/
│       ├── formatting.py   # Data formatting
│       └── display.py      # CLI display helpers
├── output/                 # Default output directory
└── docs/                   # Additional documentation
```

## License

MIT License - See LICENSE file for details.

## Support

For questions or issues, please open a GitHub issue.
