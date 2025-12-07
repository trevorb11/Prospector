"""CSV export functionality."""

import pandas as pd
from typing import List, Optional
from ..core.base import ProspectRecord


class CSVExporter:
    """Export prospects to CSV files."""

    def __init__(self, hot_threshold: int = 70):
        """
        Initialize the CSV exporter.

        Args:
            hot_threshold: Score threshold for hot prospects file
        """
        self.hot_threshold = hot_threshold

    def export(
        self,
        prospects: List[ProspectRecord],
        filepath: str,
        include_hot_file: bool = True,
    ) -> None:
        """
        Export prospects to CSV file(s).

        Args:
            prospects: List of ProspectRecord objects
            filepath: Path to output CSV file
            include_hot_file: Whether to also create a hot prospects file
        """
        if not prospects:
            print("No prospects to export!")
            return

        # Convert to DataFrame
        df = pd.DataFrame([p.to_dict() for p in prospects])

        # Sort by score
        if "Score" in df.columns:
            df = df.sort_values("Score", ascending=False)

        # Export all prospects
        df.to_csv(filepath, index=False)
        print(f"Exported {len(df)} prospects to {filepath}")

        # Export hot prospects
        if include_hot_file and "Score" in df.columns:
            hot_df = df[df["Score"] >= self.hot_threshold]
            if not hot_df.empty:
                hot_filepath = filepath.replace(".csv", "_HOT.csv")
                hot_df.to_csv(hot_filepath, index=False)
                print(f"Exported {len(hot_df)} hot prospects to {hot_filepath}")
