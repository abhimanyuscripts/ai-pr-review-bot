"""Orchestration: fetch PR -> rule-based signals -> LLM review -> combine -> comment + label."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Callable

from . import llm
from .github_client import GitHubClient
from .http import HTTPError
from .prompt import SYSTEM_PROMPT, build_user_prompt
from .render import render_comment
from .review import combine_risk, normalize_review, parse_llm_json
from .signals import compute_signals, files_from_api


@dataclass
class Settings:
    repo: str
    pr_number: int
    github_token: str | None = None
    provider: str = "auto"
    gemini_api_key: str | None = None
    anthropic_api_key: str | None = None
    gemini_models: list[str] = field(default_factory=lambda: list(llm.DEFAULT_GEMINI_MODELS))
    claude_model: str = llm.DEFAULT_CLAUDE_MODEL
    max_diff_chars: int = 60_000
    dry_run: bool = False
    fail_on_high: bool = False

    @classmethod
    def from_env(cls, repo: str | None = None, pr_number: int | None = None, **overrides) -> "Settings":
        env = os.environ
        models = [m.strip() for m in env.get("GEMINI_MODEL", "").split(",") if m.strip()]
        settings = cls(
            repo=repo or env.get("REPO") or env.get("GITHUB_REPOSITORY", ""),
            pr_number=int(pr_number or env.get("PR_NUMBER") or 0),
            github_token=env.get("GITHUB_TOKEN") or None,
            provider=env.get("LLM_PROVIDER") or "auto",
            gemini_api_key=env.get("GEMINI_API_KEY") or None,
            anthropic_api_key=env.get("ANTHROPIC_API_KEY") or None,
            gemini_models=models or list(llm.DEFAULT_GEMINI_MODELS),
            claude_model=env.get("CLAUDE_MODEL") or llm.DEFAULT_CLAUDE_MODEL,
            max_diff_chars=int(env.get("MAX_DIFF_CHARS") or 60_000),
            fail_on_high=(env.get("FAIL_ON_HIGH_RISK", "").lower() in ("1", "true", "yes")),
        )
        for key, value in overrides.items():
            if value is not None:
                setattr(settings, key, value)
        return settings


@dataclass
class Result:
    final_level: str
    comment: str
    model_used: str | None
    ai_error: str | None
    action: str  # "created", "updated", "dry-run" or "not-posted"


LLMCaller = Callable[[str, str], "tuple[str, str]"]


def make_llm_caller(settings: Settings) -> tuple[str, LLMCaller | None]:
    provider = llm.resolve_provider(settings.provider, settings.gemini_api_key, settings.anthropic_api_key)
    if provider == "gemini":
        return provider, lambda system, user: llm.call_gemini(
            settings.gemini_api_key, system, user, settings.gemini_models
        )
    if provider == "anthropic":
        return provider, lambda system, user: llm.call_claude(
            settings.anthropic_api_key, system, user, settings.claude_model
        )
    return provider, None


def run_review(settings: Settings, client: GitHubClient | None = None, call_llm: LLMCaller | None = None) -> Result:
    client = client or GitHubClient(settings.repo, settings.github_token)
    if call_llm is None:
        provider, call_llm = make_llm_caller(settings)
        print(f"LLM provider: {provider}")

    pr = client.get_pull_request(settings.pr_number)
    files = files_from_api(client.get_files(settings.pr_number))
    signals = compute_signals(files)
    print(f"PR #{settings.pr_number}: {len(files)} file(s), rule-based score {signals.score} ({signals.level})")

    review, model_used, ai_error, omitted = None, None, None, []
    if call_llm is None:
        ai_error = "no LLM API key configured"
    else:
        user_prompt, omitted = build_user_prompt(
            pr.get("title") or "", pr.get("body"), files, signals, settings.max_diff_chars
        )
        try:
            text, model_used = call_llm(SYSTEM_PROMPT, user_prompt)
            review = normalize_review(parse_llm_json(text))
            print(f"AI review from {model_used}: {review['risk_level']}, {len(review['findings'])} finding(s)")
        except (llm.LLMError, ValueError, HTTPError, OSError) as exc:
            ai_error = str(exc)[:200]
            print(f"AI review failed, falling back to rule-based checks: {ai_error}")

    final_level, note = combine_risk(review["risk_level"] if review else None, signals)
    comment = render_comment(signals, review, final_level, note, model_used, ai_error, omitted)

    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as fh:
            fh.write(comment)

    if settings.dry_run:
        return Result(final_level, comment, model_used, ai_error, "dry-run")

    try:
        action = client.upsert_comment(settings.pr_number, comment)
        client.set_risk_label(settings.pr_number, final_level)
    except HTTPError as exc:
        if exc.status != 403:
            raise
        # Pull requests from forks get a read-only token: keep the review in the job summary instead.
        print("No permission to comment on this PR (likely a fork); the review is in the job summary.")
        action = "not-posted"
    print(f"Review comment {action}; label set to risk: {final_level}")
    return Result(final_level, comment, model_used, ai_error, action)
