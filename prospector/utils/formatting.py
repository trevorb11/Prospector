"""Formatting utilities for prospect data."""

import re
from typing import Any, Optional


def format_phone(phone: Any) -> str:
    """
    Clean and format a phone number to (XXX) XXX-XXXX format.

    Args:
        phone: Phone number in any format

    Returns:
        Formatted phone number or empty string
    """
    if phone is None or phone == "":
        return ""

    # Remove all non-digits
    digits = re.sub(r"\D", "", str(phone))

    # Format as (XXX) XXX-XXXX if 10 digits
    if len(digits) == 10:
        return f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"
    elif len(digits) == 11 and digits[0] == "1":
        return f"({digits[1:4]}) {digits[4:7]}-{digits[7:]}"

    return str(phone) if phone else ""


def format_currency(amount: float) -> str:
    """
    Format a number as currency.

    Args:
        amount: Dollar amount

    Returns:
        Formatted string like "$1,234.56"
    """
    return f"${amount:,.2f}"


def clean_company_name(name: Any) -> str:
    """
    Standardize company name for comparison/matching.

    Args:
        name: Company name to clean

    Returns:
        Cleaned company name
    """
    if name is None or not str(name).strip():
        return ""

    name = str(name).upper()

    # Remove common business suffixes
    suffixes = [
        " LLC", " INC", " CORP", " CO", " TRUCKING", " TRANSPORT",
        " LOGISTICS", " ENTERPRISES", " SERVICES", " COMPANY",
        " LIMITED", " LTD", " INCORPORATED", " CORPORATION",
    ]
    for suffix in suffixes:
        name = name.replace(suffix, "")

    # Remove punctuation
    name = re.sub(r"[^\w\s]", "", name)

    # Normalize whitespace
    name = " ".join(name.split())

    return name


def truncate_string(s: str, max_length: int = 50, suffix: str = "...") -> str:
    """
    Truncate a string to a maximum length.

    Args:
        s: String to truncate
        max_length: Maximum length including suffix
        suffix: Suffix to add if truncated

    Returns:
        Truncated string
    """
    if len(s) <= max_length:
        return s
    return s[:max_length - len(suffix)] + suffix
