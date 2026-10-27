"""Render the review as a GitHub-flavoured Markdown PR comment."""

from __future__ import annotations

from .signals import Signals

MARKER = "<!-- ai-pr-review-bot -->"

BADGES = {"low": "🟢 Low risk", "medium": "🟡 Medium risk", "high": "🔴 High risk"}
SEVERITY_ICONS = {"low": "🟢", "medium": "🟡", "high": "🔴"}
VERDICT_TEXT = {
    "approve": "Looks good to merge after a quick human check.",
    "comment": "Mergeable, but address the comments first.",
    "request_changes": "Changes recommended before merging.",
}


def _cell(text: str) -> str:
    """Make text safe inside a Markdown table cell."""
    return str(text).replace("|", "\\|").replace("\n", " ").strip() or "—"


def _file_list(files: list[str], limit: int = 4) -> str:
    shown = ", ".join(f"`{f}`" for f in files[:limit])
    return shown + (f" +{len(files) - limit} more" if len(files) > limit else "")


def render_comment(
    signals: Signals,
    review: dict | None,
    final_level: str,
    risk_note: str,
    model_used: str | None = None,
    ai_error: str | None = None,
    omitted_files: list[str] | None = None,
) -> str:
    out = [MARKER, f"## 🤖 AI PR Review: {BADGES[final_level]}", ""]

    if review:
        out += [f"**Summary:** {review['summary']}", ""]
        if review["risk_reasons"]:
            out.append("**Why this risk level**")
            out += [f"- {r}" for r in review["risk_reasons"]]
            out.append("")
    elif ai_error:
        out += [f"> ⚠️ The AI review could not run ({ai_error}). Showing rule-based checks only.", ""]

    out += ["### Automated checks", "", "| Check | Result |", "|---|---|"]
    out.append(
        f"| Size | +{signals.additions} / −{signals.deletions} lines across {signals.files_changed} file(s) |"
    )
    if signals.sensitive:
        areas = "; ".join(f"{cat}: {_file_list(files, 2)}" for cat, files in sorted(signals.sensitive.items()))
        out.append(f"| Sensitive areas | {_cell(areas)} |")
    else:
        out.append("| Sensitive areas | none detected |")
    if signals.docs_only:
        tests = "not needed (documentation only)"
    elif signals.test_files:
        tests = f"✅ updated ({_file_list(signals.test_files, 3)})"
    elif signals.code_files:
        tests = "⚠️ code changed without test changes"
    else:
        tests = "no code changes"
    out.append(f"| Tests | {_cell(tests)} |")
    if signals.possible_secrets:
        out.append(f"| Possible secrets | ⚠️ {_cell(', '.join(f'`{s}`' for s in signals.possible_secrets[:5]))} |")
    else:
        out.append("| Possible secrets | none found |")
    out.append(f"| Rule-based score | {signals.score}/100 ({signals.level}) |")
    out.append("")

    if review:
        if review["findings"]:
            out += ["### Findings", "", "| | Location | Issue | Suggestion |", "|---|---|---|---|"]
            for f in review["findings"]:
                location = f"`{f['file']}`" + (f" L{f['line']}" if f["line"] else "") if f["file"] else "—"
                out.append(
                    f"| {SEVERITY_ICONS[f['severity']]} | {_cell(location)} | {_cell(f['issue'])} | {_cell(f['suggestion'])} |"
                )
            out.append("")
        else:
            out += ["### Findings", "", "No issues found in the diff.", ""]
        if review["tests_to_add"]:
            out.append("### Suggested tests")
            out += [f"- [ ] {t}" for t in review["tests_to_add"]]
            out.append("")
        out += [f"**Verdict:** {VERDICT_TEXT[review['verdict']]}", ""]

    footer = [f"Final risk: {risk_note}"]
    if model_used:
        footer.append(f"model: `{model_used}`")
    if omitted_files:
        footer.append(f"{len(omitted_files)} file(s) not sent to the AI (lockfile, binary or size limit)")
    footer.append("automated review; a human should still approve")
    out.append("<sub>" + " · ".join(footer) + "</sub>")
    return "\n".join(out) + "\n"
