"""
Lead enrichment functionality for enhancing prospect data.

This module provides tools to enrich existing lead lists with
data from industry-specific sources.
"""

import pandas as pd
from typing import Any, Dict, List, Optional, Callable
from difflib import SequenceMatcher
import re
import time


class LeadEnricher:
    """
    Enrich existing lead lists with data from industry sources.

    This class takes a list of leads (with minimal info like company name
    and state) and attempts to match them against industry databases to
    add additional data points.
    """

    def __init__(
        self,
        lookup_func: Callable[[str], Optional[Dict[str, Any]]],
        name_search_func: Optional[Callable[[str, str], List[Dict[str, Any]]]] = None,
        match_threshold: float = 0.7,
        rate_limit_delay: float = 0.3,
    ):
        """
        Initialize the enricher.

        Args:
            lookup_func: Function that takes an ID and returns record data
            name_search_func: Function that takes (name, state) and returns matches
            match_threshold: Minimum similarity score for name matching (0-1)
            rate_limit_delay: Seconds to wait between API calls
        """
        self.lookup_func = lookup_func
        self.name_search_func = name_search_func
        self.match_threshold = match_threshold
        self.rate_limit_delay = rate_limit_delay

    @staticmethod
    def clean_company_name(name: str) -> str:
        """Standardize company name for matching."""
        if pd.isna(name) or not name:
            return ""
        name = str(name).upper()
        # Remove common suffixes
        suffixes = [
            " LLC", " INC", " CORP", " CO", " TRUCKING", " TRANSPORT",
            " LOGISTICS", " ENTERPRISES", " SERVICES", " COMPANY",
            " LIMITED", " LTD", " INCORPORATED",
        ]
        for suffix in suffixes:
            name = name.replace(suffix, "")
        # Remove punctuation
        name = re.sub(r"[^\w\s]", "", name)
        # Normalize whitespace
        name = " ".join(name.split())
        return name

    @staticmethod
    def similarity_score(name1: str, name2: str) -> float:
        """Calculate similarity between two company names."""
        clean1 = LeadEnricher.clean_company_name(name1)
        clean2 = LeadEnricher.clean_company_name(name2)
        if not clean1 or not clean2:
            return 0.0
        return SequenceMatcher(None, clean1, clean2).ratio()

    def enrich_single(
        self,
        record: Dict[str, Any],
        id_column: Optional[str] = None,
        name_column: Optional[str] = None,
        state_column: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Enrich a single lead record.

        Args:
            record: Dictionary containing the lead data
            id_column: Column name for industry ID (e.g., DOT number)
            name_column: Column name for company name
            state_column: Column name for state

        Returns:
            Dictionary with enrichment data and match info
        """
        result = {
            "matched": False,
            "match_method": None,
            "match_score": 0.0,
            "enriched_data": {},
        }

        # Try ID lookup first (most reliable)
        if id_column and record.get(id_column):
            id_value = str(record[id_column]).strip()
            data = self.lookup_func(id_value)
            if data:
                result["matched"] = True
                result["match_method"] = "ID Lookup"
                result["match_score"] = 1.0
                result["enriched_data"] = data
                return result

        # Fall back to name + state search
        if self.name_search_func and name_column and state_column:
            name = record.get(name_column)
            state = record.get(state_column)
            if name and state:
                candidates = self.name_search_func(str(name), str(state))
                if candidates:
                    # Find best match
                    best_match = None
                    best_score = 0.0

                    for candidate in candidates:
                        legal_score = self.similarity_score(
                            name, candidate.get("legal_name", "")
                        )
                        dba_score = self.similarity_score(
                            name, candidate.get("dba_name", "")
                        )
                        score = max(legal_score, dba_score)

                        if score > best_score and score >= self.match_threshold:
                            best_score = score
                            best_match = candidate

                    if best_match:
                        result["matched"] = True
                        result["match_method"] = "Name Match"
                        result["match_score"] = best_score
                        result["enriched_data"] = best_match

        return result

    def enrich_dataframe(
        self,
        df: pd.DataFrame,
        id_column: Optional[str] = None,
        name_column: Optional[str] = None,
        state_column: Optional[str] = None,
        prefix: str = "ENRICHED_",
        progress_callback: Optional[Callable[[int, int], None]] = None,
    ) -> pd.DataFrame:
        """
        Enrich an entire DataFrame of leads.

        Args:
            df: DataFrame containing leads to enrich
            id_column: Column name for industry ID
            name_column: Column name for company name
            state_column: Column name for state
            prefix: Prefix for enriched columns
            progress_callback: Optional callback for progress updates

        Returns:
            DataFrame with enriched columns added
        """
        enriched_records = []
        total = len(df)
        matched_count = 0

        for idx, row in df.iterrows():
            if progress_callback:
                progress_callback(idx + 1, total)

            result = self.enrich_single(
                row.to_dict(),
                id_column=id_column,
                name_column=name_column,
                state_column=state_column,
            )

            enriched_row = {
                f"{prefix}Matched": result["matched"],
                f"{prefix}Match_Method": result["match_method"] or "No Match",
                f"{prefix}Match_Score": result["match_score"],
            }

            if result["matched"]:
                matched_count += 1
                for key, value in result["enriched_data"].items():
                    enriched_row[f"{prefix}{key}"] = value

            enriched_records.append(enriched_row)

            # Rate limiting
            time.sleep(self.rate_limit_delay)

        # Merge enriched data back to original
        enriched_df = pd.DataFrame(enriched_records, index=df.index)
        result_df = pd.concat([df, enriched_df], axis=1)

        print(f"Enrichment complete: {matched_count}/{total} matched ({matched_count/total*100:.1f}%)")

        return result_df

    def auto_detect_columns(
        self, df: pd.DataFrame
    ) -> Dict[str, Optional[str]]:
        """
        Auto-detect relevant columns in a DataFrame.

        Args:
            df: DataFrame to analyze

        Returns:
            Dictionary with detected column names
        """
        columns_lower = {col.lower(): col for col in df.columns}

        detected = {
            "id_column": None,
            "name_column": None,
            "state_column": None,
        }

        # Find ID column (DOT, EIN, etc.)
        id_patterns = ["dot", "dot_number", "dotnumber", "usdot", "ein", "tax_id"]
        for pattern in id_patterns:
            for col_lower, col in columns_lower.items():
                if pattern in col_lower:
                    detected["id_column"] = col
                    break
            if detected["id_column"]:
                break

        # Find company name column
        name_patterns = ["company", "name", "business", "legal"]
        for pattern in name_patterns:
            for col_lower, col in columns_lower.items():
                if pattern in col_lower and "state" not in col_lower:
                    detected["name_column"] = col
                    break
            if detected["name_column"]:
                break

        # Find state column
        state_patterns = ["state", "st"]
        for pattern in state_patterns:
            for col_lower, col in columns_lower.items():
                if (
                    col_lower == pattern
                    or col_lower.endswith("_state")
                    or col_lower.endswith("state")
                ):
                    detected["state_column"] = col
                    break
            if detected["state_column"]:
                break

        return detected
