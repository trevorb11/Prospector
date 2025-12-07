"""Tests for the scoring engine."""

import pytest
from prospector.core.scoring import ScoringEngine, ScoringRule, RuleType
from prospector.core.base import ProspectRecord


class TestScoringEngine:
    """Tests for ScoringEngine class."""

    def test_base_score(self):
        """Test that base score is applied."""
        engine = ScoringEngine(base_score=50)
        record = ProspectRecord(company_name="Test Co")
        scored = engine.score(record)
        assert scored.prospect_score == 50

    def test_range_rule(self):
        """Test range-based scoring rule."""
        rules = [
            ScoringRule(
                name="fleet_sweet_spot",
                field="business_size_metric",
                rule_type=RuleType.RANGE,
                params={"min": 5, "max": 20},
                points=30,
            )
        ]
        engine = ScoringEngine(rules=rules, base_score=50)

        # Should match
        record = ProspectRecord(company_name="Test Co", business_size_metric=10)
        scored = engine.score(record)
        assert scored.prospect_score == 80  # 50 + 30

        # Should not match
        record2 = ProspectRecord(company_name="Test Co 2", business_size_metric=25)
        scored2 = engine.score(record2)
        assert scored2.prospect_score == 50  # base only

    def test_presence_rule(self):
        """Test presence-based scoring rule."""
        rules = [
            ScoringRule(
                name="has_phone",
                field="phone",
                rule_type=RuleType.PRESENCE,
                points=10,
            )
        ]
        engine = ScoringEngine(rules=rules, base_score=50)

        # Has phone
        record = ProspectRecord(company_name="Test Co", phone="(555) 123-4567")
        scored = engine.score(record)
        assert scored.prospect_score == 60

        # No phone
        record2 = ProspectRecord(company_name="Test Co 2", phone=None)
        scored2 = engine.score(record2)
        assert scored2.prospect_score == 50

    def test_score_breakdown(self):
        """Test that score breakdown is recorded."""
        rules = [
            ScoringRule(
                name="has_phone",
                field="phone",
                rule_type=RuleType.PRESENCE,
                points=10,
            ),
            ScoringRule(
                name="fleet_size",
                field="business_size_metric",
                rule_type=RuleType.RANGE,
                params={"min": 5, "max": 20},
                points=30,
            ),
        ]
        engine = ScoringEngine(rules=rules, base_score=50)

        record = ProspectRecord(
            company_name="Test Co",
            phone="(555) 123-4567",
            business_size_metric=10,
        )
        scored = engine.score(record)

        assert "base" in scored.score_breakdown
        assert "has_phone" in scored.score_breakdown
        assert "fleet_size" in scored.score_breakdown
        assert scored.score_breakdown["base"] == 50
        assert scored.score_breakdown["has_phone"] == 10
        assert scored.score_breakdown["fleet_size"] == 30

    def test_score_capped_at_100(self):
        """Test that scores are capped at 100."""
        rules = [
            ScoringRule(
                name="rule1",
                field="phone",
                rule_type=RuleType.PRESENCE,
                points=30,
            ),
            ScoringRule(
                name="rule2",
                field="email",
                rule_type=RuleType.PRESENCE,
                points=30,
            ),
        ]
        engine = ScoringEngine(rules=rules, base_score=50)

        record = ProspectRecord(
            company_name="Test Co",
            phone="555-1234",
            email="test@test.com",
        )
        scored = engine.score(record)
        assert scored.prospect_score == 100  # capped


class TestProspectRecord:
    """Tests for ProspectRecord class."""

    def test_to_dict(self):
        """Test conversion to dictionary."""
        record = ProspectRecord(
            company_name="Test Trucking LLC",
            dba_name="Test Trucking",
            phone="(555) 123-4567",
            city="Miami",
            state="FL",
            business_size_metric=15,
            business_size_label="Trucks",
        )

        data = record.to_dict()

        assert data["Company Name"] == "Test Trucking LLC"
        assert data["DBA Name"] == "Test Trucking"
        assert data["Phone"] == "(555) 123-4567"
        assert data["City"] == "Miami"
        assert data["State"] == "FL"
        assert data["Trucks"] == 15

    def test_industry_data_included(self):
        """Test that industry-specific data is included in dict."""
        record = ProspectRecord(
            company_name="Test Co",
            industry_data={
                "DOT Number": "1234567",
                "MC Number": "MC-123456",
            },
        )

        data = record.to_dict()

        assert data["DOT Number"] == "1234567"
        assert data["MC Number"] == "MC-123456"
