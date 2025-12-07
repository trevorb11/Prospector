"""Excel export functionality."""

import pandas as pd
from typing import List, Optional
from ..core.base import ProspectRecord


class ExcelExporter:
    """Export prospects to Excel files with multiple sheets."""

    def __init__(self, hot_threshold: int = 70, medium_threshold: int = 50):
        """
        Initialize the Excel exporter.

        Args:
            hot_threshold: Score threshold for hot prospects
            medium_threshold: Score threshold for medium prospects
        """
        self.hot_threshold = hot_threshold
        self.medium_threshold = medium_threshold

    def export(
        self,
        prospects: List[ProspectRecord],
        filepath: str,
        include_summary: bool = True,
    ) -> None:
        """
        Export prospects to Excel file with multiple sheets.

        Args:
            prospects: List of ProspectRecord objects
            filepath: Path to output Excel file
            include_summary: Whether to include a summary sheet
        """
        if not prospects:
            print("No prospects to export!")
            return

        # Convert to DataFrame
        df = pd.DataFrame([p.to_dict() for p in prospects])

        # Sort by score
        if "Score" in df.columns:
            df = df.sort_values("Score", ascending=False)

        with pd.ExcelWriter(filepath, engine="openpyxl") as writer:
            # All prospects
            df.to_excel(writer, sheet_name="All Prospects", index=False)

            if "Score" in df.columns:
                # Hot prospects
                hot_df = df[df["Score"] >= self.hot_threshold]
                if not hot_df.empty:
                    hot_df.to_excel(writer, sheet_name=f"Hot ({self.hot_threshold}+)", index=False)

                # Medium prospects
                medium_df = df[
                    (df["Score"] >= self.medium_threshold)
                    & (df["Score"] < self.hot_threshold)
                ]
                if not medium_df.empty:
                    medium_df.to_excel(
                        writer,
                        sheet_name=f"Medium ({self.medium_threshold}-{self.hot_threshold-1})",
                        index=False,
                    )

                # Lower prospects
                lower_df = df[df["Score"] < self.medium_threshold]
                if not lower_df.empty:
                    lower_df.to_excel(writer, sheet_name=f"Lower (<{self.medium_threshold})", index=False)

            # Summary sheet
            if include_summary:
                summary_data = self._generate_summary(df)
                pd.DataFrame(summary_data).to_excel(writer, sheet_name="Summary", index=False)

            # Scoring guide
            scoring_guide = self._get_scoring_guide()
            pd.DataFrame(scoring_guide).to_excel(writer, sheet_name="Scoring Guide", index=False)

        print(f"Exported to {filepath}")

    def _generate_summary(self, df: pd.DataFrame) -> dict:
        """Generate summary statistics."""
        has_score = "Score" in df.columns
        has_phone = "Phone" in df.columns

        summary = {
            "Metric": [],
            "Value": [],
        }

        summary["Metric"].append("Total Prospects")
        summary["Value"].append(len(df))

        if has_score:
            summary["Metric"].append(f"Hot Prospects ({self.hot_threshold}+)")
            summary["Value"].append(len(df[df["Score"] >= self.hot_threshold]))

            summary["Metric"].append(f"Medium Prospects ({self.medium_threshold}-{self.hot_threshold-1})")
            summary["Value"].append(
                len(df[(df["Score"] >= self.medium_threshold) & (df["Score"] < self.hot_threshold)])
            )

            summary["Metric"].append(f"Lower Prospects (<{self.medium_threshold})")
            summary["Value"].append(len(df[df["Score"] < self.medium_threshold]))

            summary["Metric"].append("Average Score")
            summary["Value"].append(round(df["Score"].mean(), 1))

        if has_phone:
            with_phone = len(df[df["Phone"].notna() & (df["Phone"] != "")])
            summary["Metric"].append("With Phone Number")
            summary["Value"].append(with_phone)

            summary["Metric"].append("Phone Coverage %")
            summary["Value"].append(f"{with_phone / len(df) * 100:.1f}%")

        if "State" in df.columns:
            summary["Metric"].append("")
            summary["Value"].append("")
            summary["Metric"].append("BY STATE")
            summary["Value"].append("")

            for state, count in df["State"].value_counts().items():
                summary["Metric"].append(f"  {state}")
                summary["Value"].append(count)

        return summary

    def _get_scoring_guide(self) -> dict:
        """Return the scoring guide data."""
        return {
            "Component": [
                "PROSPECT SCORING GUIDE",
                "",
                "Base Score",
                "Fleet Size: 5-20 trucks",
                "Fleet Size: 2-4 trucks",
                "Fleet Size: 21-35 trucks",
                "Fleet Size: 1 truck",
                "Has Phone Number",
                "Has MC Authority",
                "",
                "SCORE INTERPRETATION",
                f"{self.hot_threshold}+ (HOT)",
                f"{self.medium_threshold}-{self.hot_threshold-1}",
                f"<{self.medium_threshold}",
            ],
            "Points": [
                "",
                "",
                "+50",
                "+30",
                "+20",
                "+15",
                "+5",
                "+10",
                "+10",
                "",
                "",
                "High priority - phone call first",
                "Medium priority - email sequence",
                "Lower priority - nurture sequence",
            ],
            "Description": [
                "",
                "",
                "All prospects start with 50 points",
                "Sweet spot for financing deals",
                "Small but established",
                "Medium fleet",
                "Owner-operator",
                "Contact info available",
                "For-hire carrier indicator",
                "",
                "",
                "",
                "",
                "",
            ],
        }
