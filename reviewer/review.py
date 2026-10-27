"""Parse, validate and combine the LLM's review with the rule-based signals."""

from __future__ import annotations

import json
import re

from .signals import LEVELS, Signals

VERDICTS = ("approve", "comment", "request_changes")


def parse_llm_json(text: str) -> dict:
    """Extract a JSON object from model output, tolerating code fences or stray text around it."""
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.I).strip()
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start == -1 or end <= start:
            raise ValueError("model output contains no JSON object") from None
        try:
            data = json.loads(cleaned[start : end + 1])
        except json.JSONDecodeError as exc:
            raise ValueError(f"model output is not valid JSON: {exc}") from None
    if not isinstance(data, dict):
        raise ValueError("model output JSON is not an object")
    return data


def _level(value, default: str = "medium") -> str:
    value = str(value or "").strip().lower()
    return value if value in LEVELS else default


def _text(value, limit: int) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def normalize_review(data: dict) -> dict:
    """Coerce the model's JSON into a known-good shape, so rendering never breaks."""
    findings = []
    for item in (data.get("findings") or [])[:8]:
        if not isinstance(item, dict) or not item.get("issue"):
            continue
        line = item.get("line")
        try:
            line = int(line) if line not in (None, "", "null") else None
        except (TypeError, ValueError):
            line = None
        findings.append(
            {
                "file": _text(item.get("file"), 200),
                "line": line,
                "severity": _level(item.get("severity")),
                "issue": _text(item.get("issue"), 300),
                "suggestion": _text(item.get("suggestion"), 300),
            }
        )
    findings.sort(key=lambda f: -LEVELS.index(f["severity"]))

    verdict = str(data.get("verdict") or "comment").strip().lower()
    return {
        "summary": _text(data.get("summary") or "No summary returned.", 600),
        "risk_level": _level(data.get("risk_level")),
        "risk_reasons": [_text(r, 200) for r in (data.get("risk_reasons") or [])[:5] if r],
        "findings": findings,
        "tests_to_add": [_text(t, 200) for t in (data.get("tests_to_add") or [])[:5] if t],
        "verdict": verdict if verdict in VERDICTS else "comment",
    }


def combine_risk(ai_level: str | None, signals: Signals) -> tuple[str, str]:
    """Final risk = the AI's level, but never lower than a floor set by the rule-based checks.

    Floor = one step below the rule-based level (so a rule-based "high" forces at least
    "medium"), and a possible hardcoded secret always forces "high".
    Returns (final_level, explanation).
    """
    floor = max(LEVELS.index(signals.level) - 1, 0)
    if signals.possible_secrets:
        floor = LEVELS.index("high")
    if ai_level is None:
        return signals.level, "rule-based checks only (AI review unavailable)"
    ai_index = LEVELS.index(ai_level)
    final = max(ai_index, floor)
    if final > ai_index:
        return LEVELS[final], f"raised from the AI's \"{ai_level}\" by the rule-based checks"
    return LEVELS[final], "AI verdict, checked against the rule-based floor"
