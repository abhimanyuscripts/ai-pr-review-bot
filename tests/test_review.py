import unittest

from reviewer.review import combine_risk, normalize_review, parse_llm_json
from reviewer.signals import Signals


class ParseTest(unittest.TestCase):
    def test_plain_json(self):
        self.assertEqual(parse_llm_json('{"risk_level": "low"}'), {"risk_level": "low"})

    def test_fenced_json(self):
        self.assertEqual(parse_llm_json('```json\n{"a": 1}\n```'), {"a": 1})

    def test_json_with_surrounding_text(self):
        self.assertEqual(parse_llm_json('Here you go:\n{"a": {"b": 2}}\nThanks'), {"a": {"b": 2}})

    def test_rejects_non_json(self):
        with self.assertRaises(ValueError):
            parse_llm_json("I could not review this.")


class NormalizeTest(unittest.TestCase):
    def test_bad_values_are_coerced(self):
        review = normalize_review(
            {
                "summary": "  Adds   login  ",
                "risk_level": "CRITICAL",
                "findings": [
                    {"file": "a.py", "line": "12", "severity": "low", "issue": "x", "suggestion": "y"},
                    {"file": "b.py", "line": "n/a", "severity": "HIGH", "issue": "z"},
                    {"file": "c.py"},  # no issue: dropped
                    "not a dict",
                ],
                "verdict": "merge it!",
            }
        )
        self.assertEqual(review["summary"], "Adds login")
        self.assertEqual(review["risk_level"], "medium")
        self.assertEqual(review["verdict"], "comment")
        self.assertEqual([f["file"] for f in review["findings"]], ["b.py", "a.py"])  # high severity first
        self.assertEqual(review["findings"][1]["line"], 12)
        self.assertIsNone(review["findings"][0]["line"])


class CombineRiskTest(unittest.TestCase):
    def test_ai_level_kept_when_above_floor(self):
        self.assertEqual(combine_risk("high", Signals(level="low"))[0], "high")

    def test_rule_based_high_raises_ai_low_to_medium(self):
        level, note = combine_risk("low", Signals(level="high"))
        self.assertEqual(level, "medium")
        self.assertIn("raised", note)

    def test_secret_always_high(self):
        self.assertEqual(combine_risk("low", Signals(level="high", possible_secrets=["a.py:1"]))[0], "high")

    def test_no_ai_uses_rule_based_level(self):
        self.assertEqual(combine_risk(None, Signals(level="medium"))[0], "medium")


if __name__ == "__main__":
    unittest.main()
