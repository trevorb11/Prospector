"""Display utilities for CLI output."""

from typing import Any, Dict, Optional
import sys


def print_summary(summary: Dict[str, Any], industry: str = "Unknown") -> None:
    """
    Print a formatted summary of prospect results.

    Args:
        summary: Dictionary with summary statistics
        industry: Name of the industry
    """
    print()
    print("=" * 60)
    print(f"  PROSPECT LIST SUMMARY - {industry}")
    print("=" * 60)

    print(f"\n  Total Prospects: {summary.get('total', 0):,}")

    if summary.get("hot_count") is not None:
        print(f"\n  Score Distribution:")
        print(f"    Hot (70+):     {summary['hot_count']:,}")
        print(f"    Medium (50-69): {summary.get('medium_count', 0):,}")
        print(f"    Lower (<50):    {summary.get('low_count', 0):,}")

    if summary.get("avg_score") is not None:
        print(f"\n  Average Score: {summary['avg_score']}")

    if summary.get("with_phone") is not None:
        total = summary.get("total", 1)
        with_phone = summary["with_phone"]
        pct = (with_phone / total * 100) if total > 0 else 0
        print(f"\n  With Phone Numbers: {with_phone:,} ({pct:.1f}%)")

    if summary.get("by_state"):
        print(f"\n  By State:")
        for state, count in sorted(summary["by_state"].items(), key=lambda x: -x[1]):
            print(f"    {state}: {count:,}")

    print()
    print("=" * 60)


def print_progress(current: int, total: int, prefix: str = "Progress", width: int = 40) -> None:
    """
    Print a progress bar.

    Args:
        current: Current progress value
        total: Total value
        prefix: Text prefix
        width: Width of the progress bar
    """
    pct = current / total if total > 0 else 0
    filled = int(width * pct)
    bar = "=" * filled + "-" * (width - filled)
    sys.stdout.write(f"\r  {prefix}: [{bar}] {current}/{total} ({pct*100:.1f}%)")
    sys.stdout.flush()
    if current >= total:
        print()


def print_banner(title: str, subtitle: Optional[str] = None) -> None:
    """
    Print a banner header.

    Args:
        title: Main title
        subtitle: Optional subtitle
    """
    print()
    print("=" * 60)
    print(f"  {title}")
    if subtitle:
        print(f"  {subtitle}")
    print("=" * 60)
    print()
