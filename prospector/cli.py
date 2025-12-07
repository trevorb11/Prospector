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
