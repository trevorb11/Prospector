"""
Flexible scoring engine for prospect evaluation.

The scoring system allows configurable rules that can be customized
per industry while maintaining consistent evaluation logic.
"""

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Union
from enum import Enum


class RuleType(Enum):
    """Types of scoring rules."""
    RANGE = "range"           # Score based on value falling in range
    PRESENCE = "presence"     # Score if field has a value
    EQUALS = "equals"         # Score if field equals specific value
    CONTAINS = "contains"     # Score if field contains substring
    CUSTOM = "custom"         # Custom scoring function


@dataclass
class ScoringRule:
    """
    A single scoring rule definition.

    Examples:
        # Fleet size sweet spot (5-20 trucks = +30 points)
        ScoringRule(
            name="fleet_sweet_spot",
            field="business_size_metric",
            rule_type=RuleType.RANGE,
            params={"min": 5, "max": 20},
            points=30,
            description="Sweet spot for financing deals"
        )

        # Has phone number (+10 points)
        ScoringRule(
            name="has_phone",
            field="phone",
            rule_type=RuleType.PRESENCE,
            points=10,
            description="Contact info available"
        )
    """
    name: str
    field: str
    rule_type: RuleType
    points: int
    description: str = ""
    params: Dict[str, Any] = field(default_factory=dict)
    custom_func: Optional[Callable] = None

    def evaluate(self, record: Any) -> int:
        """
        Evaluate this rule against a prospect record.

        Args:
            record: ProspectRecord to evaluate

        Returns:
            Points awarded (0 if rule doesn't match)
        """
        # Get the field value
        if hasattr(record, self.field):
            value = getattr(record, self.field)
        elif hasattr(record, "industry_data") and self.field in record.industry_data:
            value = record.industry_data[self.field]
        else:
            return 0

        # Handle None values
        if value is None:
            return 0

        # Evaluate based on rule type
        if self.rule_type == RuleType.RANGE:
            return self._evaluate_range(value)
        elif self.rule_type == RuleType.PRESENCE:
            return self._evaluate_presence(value)
        elif self.rule_type == RuleType.EQUALS:
            return self._evaluate_equals(value)
        elif self.rule_type == RuleType.CONTAINS:
            return self._evaluate_contains(value)
        elif self.rule_type == RuleType.CUSTOM:
            return self._evaluate_custom(record)

        return 0

    def _evaluate_range(self, value: Union[int, float]) -> int:
        """Check if value falls within the specified range."""
        try:
            num_value = float(value)
            min_val = self.params.get("min", float("-inf"))
            max_val = self.params.get("max", float("inf"))
            if min_val <= num_value <= max_val:
                return self.points
        except (ValueError, TypeError):
            pass
        return 0

    def _evaluate_presence(self, value: Any) -> int:
        """Check if field has a non-empty value."""
        if value and str(value).strip():
            return self.points
        return 0

    def _evaluate_equals(self, value: Any) -> int:
        """Check if field equals the target value."""
        target = self.params.get("value")
        if str(value).upper() == str(target).upper():
            return self.points
        return 0

    def _evaluate_contains(self, value: Any) -> int:
        """Check if field contains the target substring."""
        target = self.params.get("value", "")
        if target.upper() in str(value).upper():
            return self.points
        return 0

    def _evaluate_custom(self, record: Any) -> int:
        """Run custom scoring function."""
        if self.custom_func:
            try:
                return self.custom_func(record, self.params)
            except Exception:
                pass
        return 0


class ScoringEngine:
    """
    Engine for scoring prospects based on configurable rules.

    The engine applies a base score plus all matching rule points.
    """

    DEFAULT_BASE_SCORE = 50

    def __init__(
        self,
        rules: Optional[List[Union[ScoringRule, Dict[str, Any]]]] = None,
        base_score: int = DEFAULT_BASE_SCORE,
    ):
        """
        Initialize the scoring engine.

        Args:
            rules: List of ScoringRule objects or rule dictionaries
            base_score: Starting score for all prospects
        """
        self.base_score = base_score
        self.rules: List[ScoringRule] = []

        if rules:
            for rule in rules:
                if isinstance(rule, ScoringRule):
                    self.rules.append(rule)
                elif isinstance(rule, dict):
                    self.rules.append(self._dict_to_rule(rule))

    def _dict_to_rule(self, rule_dict: Dict[str, Any]) -> ScoringRule:
        """Convert a dictionary to a ScoringRule object."""
        rule_type = rule_dict.get("rule_type", "presence")
        if isinstance(rule_type, str):
            rule_type = RuleType(rule_type)

        return ScoringRule(
            name=rule_dict.get("name", "unnamed"),
            field=rule_dict.get("field", ""),
            rule_type=rule_type,
            points=rule_dict.get("points", 0),
            description=rule_dict.get("description", ""),
            params=rule_dict.get("params", {}),
        )

    def add_rule(self, rule: Union[ScoringRule, Dict[str, Any]]) -> None:
        """Add a scoring rule."""
        if isinstance(rule, dict):
            rule = self._dict_to_rule(rule)
        self.rules.append(rule)

    def score(self, record: Any) -> Any:
        """
        Score a prospect record.

        Args:
            record: ProspectRecord to score

        Returns:
            The record with prospect_score and score_breakdown populated
        """
        total_score = self.base_score
        breakdown = {"base": self.base_score}

        for rule in self.rules:
            points = rule.evaluate(record)
            if points > 0:
                total_score += points
                breakdown[rule.name] = points

        # Cap score at 100
        record.prospect_score = min(total_score, 100)
        record.score_breakdown = breakdown

        return record

    def get_rules_summary(self) -> List[Dict[str, Any]]:
        """Get a summary of all scoring rules."""
        return [
            {
                "name": rule.name,
                "field": rule.field,
                "points": rule.points,
                "description": rule.description,
            }
            for rule in self.rules
        ]


# Pre-defined scoring rule sets for common use cases
def get_mca_default_rules() -> List[ScoringRule]:
    """
    Get default scoring rules optimized for MCA/business financing.

    These rules prioritize:
    - Sweet spot business size (not too small, not too large)
    - Availability of contact information
    - Indicators of active business
    """
    return [
        # Fleet/business size sweet spot (5-20 units)
        ScoringRule(
            name="size_sweet_spot",
            field="business_size_metric",
            rule_type=RuleType.RANGE,
            params={"min": 5, "max": 20},
            points=30,
            description="Sweet spot for financing deals",
        ),
        # Small but established (2-4 units)
        ScoringRule(
            name="size_small_established",
            field="business_size_metric",
            rule_type=RuleType.RANGE,
            params={"min": 2, "max": 4},
            points=20,
            description="Small but established",
        ),
        # Medium size (21-35 units)
        ScoringRule(
            name="size_medium",
            field="business_size_metric",
            rule_type=RuleType.RANGE,
            params={"min": 21, "max": 35},
            points=15,
            description="Medium size business",
        ),
        # Single unit/owner-operator
        ScoringRule(
            name="size_single",
            field="business_size_metric",
            rule_type=RuleType.RANGE,
            params={"min": 1, "max": 1},
            points=5,
            description="Owner-operator",
        ),
        # Has phone number
        ScoringRule(
            name="has_phone",
            field="phone",
            rule_type=RuleType.PRESENCE,
            points=10,
            description="Contact info available",
        ),
        # Has email
        ScoringRule(
            name="has_email",
            field="email",
            rule_type=RuleType.PRESENCE,
            points=5,
            description="Email available",
        ),
    ]
