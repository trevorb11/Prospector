"""
Command-line interface for Prospector.

Usage:
    prospector trucking [OPTIONS]     - Find trucking prospects
    prospector enrich [OPTIONS]       - Enrich existing lead list
    prospector lookup DOT_NUMBER      - Look up a specific company
"""

import click
import os
from datetime import datetime
from typing import Optional


@click.group()
@click.version_option(version="1.0.0")
def cli():
    """
    Prospector - Industry Lead Finder for MCA/Business Financing

    Find and score business prospects across multiple industries
    using public data sources.
    """
    pass


@cli.command()
@click.option(
    "--states", "-s",
    default="FL,GA,TX,CA,IL,NC,TN,OH,PA,NJ,NY",
    help="Comma-separated list of state abbreviations",
)
@click.option(
    "--min-trucks", "-m",
    default=1,
    type=int,
    help="Minimum fleet size (power units)",
)
@click.option(
    "--max-trucks", "-M",
    default=50,
    type=int,
    help="Maximum fleet size (power units)",
)
@click.option(
    "--output", "-o",
    default=None,
    help="Output file path (default: trucking_prospects_YYYYMMDD.csv)",
)
@click.option(
    "--format", "-f",
    type=click.Choice(["csv", "excel"]),
    default="csv",
    help="Output format",
)
@click.option(
    "--hot-threshold",
    default=70,
    type=int,
    help="Score threshold for hot prospects",
)
@click.option(
    "--app-token",
    envvar="SOCRATA_APP_TOKEN",
    default=None,
    help="Socrata API app token for higher rate limits",
)
def trucking(
    states: str,
    min_trucks: int,
    max_trucks: int,
    output: Optional[str],
    format: str,
    hot_threshold: int,
    app_token: Optional[str],
):
    """
    Find trucking company prospects from FMCSA database.

    Pulls motor carrier data from the DOT Open Data Portal and filters
    based on location and fleet size. Results are scored based on
    ideal customer profile for equipment financing.

    Examples:

        # Basic usage - all default states
        prospector trucking

        # Specific states with fleet size filter
        prospector trucking -s FL,GA,TX -m 5 -M 25

        # Export to Excel
        prospector trucking -f excel -o my_prospects.xlsx
    """
    from prospector.industries.trucking import TruckingProspector
    from prospector.utils.display import print_banner, print_summary

    print_banner(
        "FMCSA TRUCKING PROSPECT FINDER",
        "For Today Capital Group"
    )

    # Parse states
    state_list = [s.strip().upper() for s in states.split(",")]

    # Build config
    config = {
        "target_states": state_list,
        "min_power_units": min_trucks,
        "max_power_units": max_trucks,
        "app_token": app_token,
    }

    # Run prospector
    prospector = TruckingProspector(config)
    prospects = prospector.run(score=True)

    if not prospects:
        click.echo("\nNo prospects found matching your criteria.")
        return

    # Print summary
    summary = prospector.get_summary()
    print_summary(summary, "Trucking")

    # Determine output filename
    if not output:
        date_str = datetime.now().strftime("%Y%m%d")
        ext = "xlsx" if format == "excel" else "csv"
        output = f"trucking_prospects_{date_str}.{ext}"

    # Export
    if format == "excel":
        prospector.export_excel(output, hot_threshold=hot_threshold)
    else:
        prospector.export_csv(output, hot_threshold=hot_threshold)

    click.echo(f"\n  Output saved to: {output}")


@cli.command()
@click.option(
    "--states", "-s",
    default="FL,GA,TX,CA,IL,NC,TN,OH,PA,NJ,NY",
    help="Comma-separated list of state abbreviations",
)
@click.option(
    "--organizations-only/--include-individuals",
    default=True,
    help="Only search organization providers (default: organizations only)",
)
@click.option(
    "--specialty", "-sp",
    default=None,
    help="Filter by specialty (e.g., 'dental', 'radiology', 'surgery')",
)
@click.option(
    "--output", "-o",
    default=None,
    help="Output file path (default: healthcare_prospects_YYYYMMDD.csv)",
)
@click.option(
    "--format", "-f",
    type=click.Choice(["csv", "excel"]),
    default="csv",
    help="Output format",
)
@click.option(
    "--hot-threshold",
    default=70,
    type=int,
    help="Score threshold for hot prospects",
)
def healthcare(
    states: str,
    organizations_only: bool,
    specialty: Optional[str],
    output: Optional[str],
    format: str,
    hot_threshold: int,
):
    """
    Find healthcare provider prospects from NPI Registry.

    Pulls provider data from the CMS NPI Registry and filters
    based on location, specialty, and organization type.
    Focuses on practices with equipment financing needs.

    Examples:

        # Basic usage - all default states, organizations only
        prospector healthcare

        # Specific states with specialty filter
        prospector healthcare -s FL,GA,TX --specialty dental

        # Include individual providers
        prospector healthcare --include-individuals

        # Export to Excel
        prospector healthcare -f excel -o healthcare_leads.xlsx
    """
    from prospector.industries.healthcare import HealthcareProspector
    from prospector.utils.display import print_banner, print_summary

    print_banner(
        "NPI REGISTRY HEALTHCARE PROSPECT FINDER",
        "For Today Capital Group"
    )

    # Parse states
    state_list = [s.strip().upper() for s in states.split(",")]

    # Build config
    config = {
        "target_states": state_list,
        "organization_only": organizations_only,
        "entity_types": ["2"] if organizations_only else ["1", "2"],
    }

    # Run prospector
    prospector = HealthcareProspector(config)
    prospects = prospector.run(score=True)

    if not prospects:
        click.echo("\nNo prospects found matching your criteria.")
        return

    # Print summary
    summary = prospector.get_summary()
    print_summary(summary, "Healthcare")

    # Determine output filename
    if not output:
        date_str = datetime.now().strftime("%Y%m%d")
        ext = "xlsx" if format == "excel" else "csv"
        output = f"healthcare_prospects_{date_str}.{ext}"

    # Export
    if format == "excel":
        prospector.export_excel(output, hot_threshold=hot_threshold)
    else:
        prospector.export_csv(output, hot_threshold=hot_threshold)

    click.echo(f"\n  Output saved to: {output}")


@cli.command()
@click.option(
    "--states", "-s",
    default="FL,TX,CA,GA,NC,AZ,CO,TN,OH,PA",
    help="Comma-separated list of state abbreviations",
)
@click.option(
    "--contractor-type", "-t",
    default=None,
    help="Filter by contractor type (e.g., 'general', 'electrical', 'hvac')",
)
@click.option(
    "--output", "-o",
    default=None,
    help="Output file path (default: construction_prospects_YYYYMMDD.csv)",
)
@click.option(
    "--format", "-f",
    type=click.Choice(["csv", "excel"]),
    default="csv",
    help="Output format",
)
@click.option(
    "--hot-threshold",
    default=70,
    type=int,
    help="Score threshold for hot prospects",
)
def construction(
    states: str,
    contractor_type: Optional[str],
    output: Optional[str],
    format: str,
    hot_threshold: int,
):
    """
    Find construction contractor prospects.

    Pulls contractor data from state licensing boards and business
    registries. Focuses on contractors with equipment financing needs.

    Examples:

        # Basic usage - all default states
        prospector construction

        # Specific states
        prospector construction -s FL,TX,CA

        # Filter by contractor type
        prospector construction -t electrical

        # Export to Excel
        prospector construction -f excel -o contractors.xlsx
    """
    from prospector.industries.construction import ConstructionProspector
    from prospector.utils.display import print_banner, print_summary

    print_banner(
        "CONSTRUCTION CONTRACTOR PROSPECT FINDER",
        "For Today Capital Group"
    )

    # Parse states
    state_list = [s.strip().upper() for s in states.split(",")]

    # Build config
    config = {
        "target_states": state_list,
    }

    if contractor_type:
        config["include_specialty_types"] = [contractor_type]

    # Run prospector
    prospector = ConstructionProspector(config)
    prospects = prospector.run(score=True)

    if not prospects:
        click.echo("\nNo prospects found matching your criteria.")
        return

    # Print summary
    summary = prospector.get_summary()
    print_summary(summary, "Construction")

    # Determine output filename
    if not output:
        date_str = datetime.now().strftime("%Y%m%d")
        ext = "xlsx" if format == "excel" else "csv"
        output = f"construction_prospects_{date_str}.{ext}"

    # Export
    if format == "excel":
        prospector.export_excel(output, hot_threshold=hot_threshold)
    else:
        prospector.export_csv(output, hot_threshold=hot_threshold)

    click.echo(f"\n  Output saved to: {output}")


@cli.command()
@click.option(
    "--states", "-s",
    default="FL,TX,CA,AZ,GA,NC,TN,CO,NV,WA",
    help="Comma-separated list of state abbreviations",
)
@click.option(
    "--min-aircraft", "-m",
    default=1,
    type=int,
    help="Minimum aircraft count per owner",
)
@click.option(
    "--max-aircraft", "-M",
    default=100,
    type=int,
    help="Maximum aircraft count per owner",
)
@click.option(
    "--businesses-only/--include-individuals",
    default=True,
    help="Only search business entities (default: businesses only)",
)
@click.option(
    "--turbine-only",
    is_flag=True,
    default=False,
    help="Only include turbine-powered aircraft (jets, turboprops)",
)
@click.option(
    "--output", "-o",
    default=None,
    help="Output file path (default: aviation_prospects_YYYYMMDD.csv)",
)
@click.option(
    "--format", "-f",
    type=click.Choice(["csv", "excel"]),
    default="csv",
    help="Output format",
)
@click.option(
    "--hot-threshold",
    default=70,
    type=int,
    help="Score threshold for hot prospects",
)
def aviation(
    states: str,
    min_aircraft: int,
    max_aircraft: int,
    businesses_only: bool,
    turbine_only: bool,
    output: Optional[str],
    format: str,
    hot_threshold: int,
):
    """
    Find aviation prospects from FAA Aircraft Registry.

    Pulls aircraft registration data from the FAA database and
    identifies aircraft owners and operators for financing.

    Examples:

        # Basic usage - business aircraft owners
        prospector aviation

        # Fleet operators only (2+ aircraft)
        prospector aviation -m 2

        # Turbine aircraft only (jets, turboprops)
        prospector aviation --turbine-only

        # Specific states
        prospector aviation -s FL,TX,CA,AZ

        # Export to Excel
        prospector aviation -f excel -o aviation_leads.xlsx
    """
    from prospector.industries.aviation import AviationProspector
    from prospector.utils.display import print_banner, print_summary

    print_banner(
        "FAA AIRCRAFT REGISTRY PROSPECT FINDER",
        "For Today Capital Group"
    )

    # Parse states
    state_list = [s.strip().upper() for s in states.split(",")]

    # Build config
    config = {
        "target_states": state_list,
        "min_aircraft": min_aircraft,
        "max_aircraft": max_aircraft,
    }

    # Owner types: 3=Corporation, 7=LLC, 2=Partnership
    if businesses_only:
        config["owner_types"] = ["3", "7", "2"]
    else:
        config["owner_types"] = ["1", "2", "3", "4", "7"]

    # Engine types: 2-5 are turbine types
    if turbine_only:
        config["engine_types"] = ["2", "3", "4", "5"]

    # Run prospector
    prospector = AviationProspector(config)
    prospects = prospector.run(score=True)

    if not prospects:
        click.echo("\nNo prospects found matching your criteria.")
        return

    # Print summary
    summary = prospector.get_summary()
    print_summary(summary, "Aviation")

    # Determine output filename
    if not output:
        date_str = datetime.now().strftime("%Y%m%d")
        ext = "xlsx" if format == "excel" else "csv"
        output = f"aviation_prospects_{date_str}.{ext}"

    # Export
    if format == "excel":
        prospector.export_excel(output, hot_threshold=hot_threshold)
    else:
        prospector.export_csv(output, hot_threshold=hot_threshold)

    click.echo(f"\n  Output saved to: {output}")


@cli.command()
@click.option(
    "--states", "-s",
    default="FL,TX",
    help="Comma-separated list of state abbreviations (FL, TX, NY, IL supported)",
)
@click.option(
    "--include-cities/--states-only",
    default=True,
    help="Include city-level data (NYC, Chicago) for NY and IL states",
)
@click.option(
    "--active-only/--include-inactive",
    default=True,
    help="Only include businesses with active licenses",
)
@click.option(
    "--output", "-o",
    default=None,
    help="Output file path (default: health_dept_prospects_YYYYMMDD.csv)",
)
@click.option(
    "--format", "-f",
    type=click.Choice(["csv", "excel"]),
    default="csv",
    help="Output format",
)
@click.option(
    "--hot-threshold",
    default=70,
    type=int,
    help="Score threshold for hot prospects",
)
@click.option(
    "--app-token",
    envvar="SOCRATA_APP_TOKEN",
    default=None,
    help="Socrata API app token for higher rate limits",
)
def health_dept(
    states: str,
    include_cities: bool,
    active_only: bool,
    output: Optional[str],
    format: str,
    hot_threshold: int,
    app_token: Optional[str],
):
    """
    Find restaurant/bar prospects from health department filings.

    Pulls food service establishment data from state and local health
    department databases. These businesses file for permits and inspections,
    providing verified business information.

    Supported data sources:
    - Florida DBPR (FL)
    - Texas DSHS (TX)
    - NYC DOHMH (NY with --include-cities)
    - Chicago CDPH (IL with --include-cities)

    Examples:

        # Basic usage - Florida and Texas
        prospector health-dept

        # Specific states
        prospector health-dept -s FL,TX,NY,IL

        # States only, no city-level data
        prospector health-dept -s FL,TX --states-only

        # Include inactive/expired licenses
        prospector health-dept --include-inactive

        # Export to Excel
        prospector health-dept -f excel -o restaurants.xlsx
    """
    from prospector.industries.health_dept import HealthDeptProspector
    from prospector.utils.display import print_banner, print_summary

    print_banner(
        "HEALTH DEPARTMENT FILINGS PROSPECT FINDER",
        "Restaurants, Bars & Food Service"
    )

    # Parse states
    state_list = [s.strip().upper() for s in states.split(",")]

    # Build config
    config = {
        "target_states": state_list,
        "include_cities": include_cities,
        "active_only": active_only,
        "app_token": app_token,
    }

    # Run prospector
    prospector = HealthDeptProspector(config)
    prospects = prospector.run(score=True)

    if not prospects:
        click.echo("\nNo prospects found matching your criteria.")
        return

    # Print summary
    summary = prospector.get_summary()
    print_summary(summary, "Health Dept Filings")

    # Determine output filename
    if not output:
        date_str = datetime.now().strftime("%Y%m%d")
        ext = "xlsx" if format == "excel" else "csv"
        output = f"health_dept_prospects_{date_str}.{ext}"

    # Export
    if format == "excel":
        prospector.export_excel(output, hot_threshold=hot_threshold)
    else:
        prospector.export_csv(output, hot_threshold=hot_threshold)

    click.echo(f"\n  Output saved to: {output}")


@cli.command()
@click.argument("license_number")
@click.option(
    "--state", "-s",
    default="FL",
    help="State for license lookup (FL, TX supported)",
)
@click.option(
    "--app-token",
    envvar="SOCRATA_APP_TOKEN",
    default=None,
    help="Socrata API app token",
)
def license_lookup(license_number: str, state: str, app_token: Optional[str]):
    """
    Look up a specific food establishment by license number.

    Example:

        prospector license-lookup SEA1234567 -s FL
    """
    from prospector.industries.health_dept import lookup_by_license

    click.echo(f"\nLooking up license {license_number} in {state.upper()}...")

    result = lookup_by_license(license_number, state=state, app_token=app_token)

    if result:
        click.echo("\n  Establishment Information:")
        click.echo("  " + "-" * 40)
        click.echo(f"  Business Name:   {result.get('business_name', 'N/A')}")
        if result.get('dba_name'):
            click.echo(f"  DBA Name:        {result.get('dba_name')}")
        click.echo(f"  License Number:  {result.get('license_number', 'N/A')}")
        click.echo(f"  License Type:    {result.get('license_type', 'N/A')}")
        click.echo(f"  Status:          {result.get('status', 'N/A')}")
        click.echo(f"  Address:         {result.get('address', 'N/A')}")
        click.echo(f"  City/State:      {result.get('city', '')}, {result.get('state', '')} {result.get('zip', '')}")
        click.echo(f"  Data Source:     {result.get('source', 'N/A')}")
        click.echo()
    else:
        click.echo(f"\n  No establishment found with license: {license_number}")


@cli.command()
@click.argument("city")
@click.argument("state")
@click.option(
    "--type", "-t",
    "facility_type",
    default=None,
    help="Filter by facility type (e.g., 'restaurant', 'bar')",
)
@click.option(
    "--output", "-o",
    default=None,
    help="Output CSV file",
)
@click.option(
    "--app-token",
    envvar="SOCRATA_APP_TOKEN",
    default=None,
    help="Socrata API app token",
)
def food_city(
    city: str,
    state: str,
    facility_type: Optional[str],
    output: Optional[str],
    app_token: Optional[str],
):
    """
    Get all food establishments in a specific city.

    Good for hyper-local targeting campaigns.

    Example:

        prospector food-city Miami FL
        prospector food-city Houston TX -t restaurant
    """
    from prospector.industries.health_dept import get_establishments_by_city
    import pandas as pd

    click.echo(f"\nFetching food establishments in {city}, {state.upper()}...")
    if facility_type:
        click.echo(f"  Filtering by type: {facility_type}")

    results = get_establishments_by_city(
        city=city,
        state=state,
        facility_type=facility_type,
        app_token=app_token,
    )

    if results:
        click.echo(f"\n  Found {len(results)} establishments in {city}, {state.upper()}")

        if output:
            df = pd.DataFrame(results)
            df.to_csv(output, index=False)
            click.echo(f"  Saved to: {output}")
        else:
            click.echo("\n  Top 10 establishments:\n")
            for i, est in enumerate(results[:10], 1):
                click.echo(f"  {i}. {est.get('business_name', 'N/A')}")
                click.echo(f"     Type: {est.get('license_type', 'N/A')} | Status: {est.get('status', 'N/A')}")
                click.echo(f"     {est.get('address', '')}, {est.get('city', '')}")
                click.echo()
    else:
        click.echo(f"\n  No establishments found in {city}, {state.upper()}")


@cli.command()
@click.argument("npi_number")
def npi_lookup(npi_number: str):
    """
    Look up a specific healthcare provider by NPI number.

    Example:

        prospector npi-lookup 1234567890
    """
    from prospector.industries.healthcare import lookup_by_npi

    click.echo(f"\nLooking up NPI {npi_number}...")

    result = lookup_by_npi(npi_number)

    if result:
        click.echo("\n  Provider Information:")
        click.echo("  " + "-" * 40)
        if result.get("organization_name"):
            click.echo(f"  Organization:  {result.get('organization_name', 'N/A')}")
        else:
            click.echo(f"  Provider:      {result.get('provider_name', 'N/A')}")
        click.echo(f"  NPI Number:    {result.get('npi_number', 'N/A')}")
        click.echo(f"  Entity Type:   {result.get('entity_type', 'N/A')}")
        click.echo(f"  Specialty:     {result.get('specialty', 'N/A')}")
        click.echo(f"  Phone:         {result.get('phone', 'N/A')}")
        click.echo(f"  Address:       {result.get('address', 'N/A')}")
        click.echo(f"  City/State:    {result.get('city', '')}, {result.get('state', '')} {result.get('zip', '')}")
        click.echo(f"  Enumerated:    {result.get('enumeration_date', 'N/A')}")
        click.echo()
    else:
        click.echo(f"\n  No provider found with NPI number: {npi_number}")


@cli.command()
@click.argument("n_number")
def aircraft_lookup(n_number: str):
    """
    Look up a specific aircraft by N-number.

    Example:

        prospector aircraft-lookup N12345
    """
    from prospector.industries.aviation import lookup_by_n_number

    click.echo(f"\nLooking up aircraft {n_number}...")

    result = lookup_by_n_number(n_number)

    if result and result.get("found"):
        click.echo(f"\n  Aircraft N{n_number.upper().replace('N', '')} found in FAA Registry")
        click.echo(f"  Details URL: {result.get('details_url', 'N/A')}")
        click.echo("\n  Note: For full details, use the FAA N-Number Inquiry website")
        click.echo()
    else:
        click.echo(f"\n  No aircraft found with N-number: {n_number}")


@cli.command()
@click.argument("input_file", type=click.Path(exists=True))
@click.option(
    "--output", "-o",
    default=None,
    help="Output file path (default: <input>_enriched.csv)",
)
@click.option(
    "--dot-column",
    default=None,
    help="Column name for DOT number (auto-detected if not specified)",
)
@click.option(
    "--name-column",
    default=None,
    help="Column name for company name (auto-detected if not specified)",
)
@click.option(
    "--state-column",
    default=None,
    help="Column name for state (auto-detected if not specified)",
)
@click.option(
    "--app-token",
    envvar="SOCRATA_APP_TOKEN",
    default=None,
    help="Socrata API app token for higher rate limits",
)
def enrich(
    input_file: str,
    output: Optional[str],
    dot_column: Optional[str],
    name_column: Optional[str],
    state_column: Optional[str],
    app_token: Optional[str],
):
    """
    Enrich an existing lead list with FMCSA data.

    Takes a CSV file with company names/DOT numbers and adds
    official FMCSA data including fleet size, contact info,
    and authority status.

    The input file should have at least one of:
    - A DOT number column
    - Company name AND state columns

    Examples:

        # Basic usage (auto-detect columns)
        prospector enrich my_leads.csv

        # Specify output file
        prospector enrich my_leads.csv -o enriched_leads.csv

        # Specify columns explicitly
        prospector enrich my_leads.csv --dot-column "USDOT" --name-column "Company"
    """
    from prospector.industries.trucking import TruckingEnricher
    from prospector.utils.display import print_banner

    print_banner(
        "FMCSA LEAD ENRICHMENT",
        "Enriching leads with official DOT data"
    )

    # Determine output filename
    if not output:
        base, ext = os.path.splitext(input_file)
        output = f"{base}_enriched{ext}"

    # Run enrichment
    enricher = TruckingEnricher(app_token=app_token)
    enricher.enrich_file(
        input_file=input_file,
        output_file=output,
        dot_column=dot_column,
        name_column=name_column,
        state_column=state_column,
    )


@cli.command()
@click.argument("dot_number")
@click.option(
    "--app-token",
    envvar="SOCRATA_APP_TOKEN",
    default=None,
    help="Socrata API app token",
)
def lookup(dot_number: str, app_token: Optional[str]):
    """
    Look up a specific company by DOT number.

    Example:

        prospector lookup 1234567
    """
    from prospector.industries.trucking import lookup_by_dot

    click.echo(f"\nLooking up DOT {dot_number}...")

    result = lookup_by_dot(dot_number, app_token=app_token)

    if result:
        click.echo("\n  Company Information:")
        click.echo("  " + "-" * 40)
        click.echo(f"  Legal Name:    {result.get('legal_name', 'N/A')}")
        click.echo(f"  DBA Name:      {result.get('dba_name', 'N/A')}")
        click.echo(f"  DOT Number:    {result.get('dot_number', 'N/A')}")
        click.echo(f"  MC Number:     {result.get('mc_mx_ff_numbers', 'N/A')}")
        click.echo(f"  Phone:         {result.get('telephone', 'N/A')}")
        click.echo(f"  Address:       {result.get('physical_address', 'N/A')}")
        click.echo(f"  City/State:    {result.get('physical_city', '')}, {result.get('physical_state', '')} {result.get('physical_zip', '')}")
        click.echo(f"  Power Units:   {result.get('power_units', 'N/A')}")
        click.echo(f"  Drivers:       {result.get('drivers', 'N/A')}")
        click.echo(f"  Status:        {result.get('operating_status', 'N/A')}")
        click.echo(f"  Last Updated:  {result.get('mcs150_date', 'N/A')}")
        click.echo()
    else:
        click.echo(f"\n  No company found with DOT number: {dot_number}")


@cli.command()
@click.argument("company_name")
@click.option(
    "--state", "-s",
    default=None,
    help="Filter by state abbreviation",
)
@click.option(
    "--limit", "-l",
    default=10,
    type=int,
    help="Maximum results to show",
)
@click.option(
    "--app-token",
    envvar="SOCRATA_APP_TOKEN",
    default=None,
    help="Socrata API app token",
)
def search(company_name: str, state: Optional[str], limit: int, app_token: Optional[str]):
    """
    Search for companies by name.

    Example:

        prospector search "ABC Trucking" -s FL
    """
    from prospector.industries.trucking import search_by_name

    click.echo(f"\nSearching for '{company_name}'...")
    if state:
        click.echo(f"  Filtered to state: {state}")

    results = search_by_name(company_name, state=state, limit=limit, app_token=app_token)

    if results:
        click.echo(f"\n  Found {len(results)} matching companies:\n")
        for i, company in enumerate(results[:limit], 1):
            click.echo(f"  {i}. {company.get('legal_name', 'N/A')}")
            if company.get('dba_name'):
                click.echo(f"     DBA: {company['dba_name']}")
            click.echo(f"     DOT: {company.get('dot_number', 'N/A')} | {company.get('power_units', 0)} trucks | {company.get('physical_city', '')}, {company.get('physical_state', '')}")
            click.echo(f"     Phone: {company.get('telephone', 'N/A')}")
            click.echo()
    else:
        click.echo(f"\n  No companies found matching '{company_name}'")


@cli.command()
@click.argument("city")
@click.argument("state")
@click.option(
    "--min-trucks", "-m",
    default=1,
    type=int,
    help="Minimum fleet size",
)
@click.option(
    "--max-trucks", "-M",
    default=50,
    type=int,
    help="Maximum fleet size",
)
@click.option(
    "--output", "-o",
    default=None,
    help="Output CSV file",
)
@click.option(
    "--app-token",
    envvar="SOCRATA_APP_TOKEN",
    default=None,
    help="Socrata API app token",
)
def city(
    city: str,
    state: str,
    min_trucks: int,
    max_trucks: int,
    output: Optional[str],
    app_token: Optional[str],
):
    """
    Get all carriers in a specific city.

    Good for hyper-local targeting campaigns.

    Example:

        prospector city Miami FL -m 3 -M 25
    """
    from prospector.industries.trucking import get_carriers_by_city
    import pandas as pd

    click.echo(f"\nFetching carriers in {city}, {state}...")
    click.echo(f"  Fleet size: {min_trucks}-{max_trucks} trucks")

    results = get_carriers_by_city(
        city=city,
        state=state,
        min_trucks=min_trucks,
        max_trucks=max_trucks,
        app_token=app_token,
    )

    if results:
        click.echo(f"\n  Found {len(results)} carriers in {city}, {state}")

        if output:
            df = pd.DataFrame(results)
            df.to_csv(output, index=False)
            click.echo(f"  Saved to: {output}")
        else:
            click.echo("\n  Top 10 by fleet size:\n")
            for i, company in enumerate(results[:10], 1):
                click.echo(f"  {i}. {company.get('legal_name', 'N/A')}")
                click.echo(f"     {company.get('power_units', 0)} trucks | Phone: {company.get('telephone', 'N/A')}")
                click.echo()
    else:
        click.echo(f"\n  No carriers found in {city}, {state}")


def main():
    """Entry point for the CLI."""
    cli()


if __name__ == "__main__":
    main()
