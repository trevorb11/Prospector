"""Tests for formatting utilities."""

import pytest
from prospector.utils.formatting import format_phone, clean_company_name, truncate_string


class TestFormatPhone:
    """Tests for phone number formatting."""

    def test_10_digit_phone(self):
        """Test formatting 10-digit phone numbers."""
        assert format_phone("5551234567") == "(555) 123-4567"
        assert format_phone("555-123-4567") == "(555) 123-4567"
        assert format_phone("555.123.4567") == "(555) 123-4567"
        assert format_phone("(555) 123-4567") == "(555) 123-4567"

    def test_11_digit_phone_with_1(self):
        """Test formatting 11-digit phone with leading 1."""
        assert format_phone("15551234567") == "(555) 123-4567"
        assert format_phone("1-555-123-4567") == "(555) 123-4567"

    def test_empty_phone(self):
        """Test handling empty/None phone values."""
        assert format_phone(None) == ""
        assert format_phone("") == ""

    def test_non_standard_phone(self):
        """Test handling non-standard phone formats."""
        # Should return original if can't parse
        assert format_phone("123") == "123"


class TestCleanCompanyName:
    """Tests for company name cleaning."""

    def test_removes_suffixes(self):
        """Test that common suffixes are removed."""
        assert clean_company_name("ABC Trucking LLC") == "ABC"
        assert clean_company_name("XYZ Transport Inc") == "XYZ"
        assert clean_company_name("Test Company Corp") == "TEST"

    def test_uppercase(self):
        """Test that names are uppercased."""
        assert clean_company_name("abc trucking") == "ABC"

    def test_removes_punctuation(self):
        """Test that punctuation is removed."""
        assert clean_company_name("A.B.C. Trucking") == "ABC"

    def test_normalizes_whitespace(self):
        """Test that whitespace is normalized."""
        assert clean_company_name("ABC   TRUCKING") == "ABC"

    def test_empty_values(self):
        """Test handling empty/None values."""
        assert clean_company_name(None) == ""
        assert clean_company_name("") == ""


class TestTruncateString:
    """Tests for string truncation."""

    def test_no_truncation_needed(self):
        """Test strings shorter than max length."""
        assert truncate_string("short", max_length=10) == "short"

    def test_truncation(self):
        """Test strings longer than max length."""
        assert truncate_string("a very long string", max_length=10) == "a very..."

    def test_custom_suffix(self):
        """Test custom truncation suffix."""
        assert truncate_string("long string", max_length=8, suffix="..") == "long s.."
