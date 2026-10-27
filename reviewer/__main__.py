"""Command-line entry point.

In GitHub Actions:   python3 -m reviewer        (reads REPO / PR_NUMBER / keys from the environment)
Locally, read-only:  python3 -m reviewer --repo owner/name --pr 12 --dry-run
"""

from __future__ import annotations

import argparse
import sys

from .bot import Settings, run_review
from .http import HTTPError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="reviewer", description="AI review for a GitHub pull request")
    parser.add_argument("--repo", help="owner/name (default: $REPO or $GITHUB_REPOSITORY)")
    parser.add_argument("--pr", type=int, help="pull request number (default: $PR_NUMBER)")
    parser.add_argument("--provider", choices=["auto", "gemini", "anthropic", "none"], help="LLM provider")
    parser.add_argument("--dry-run", action="store_true", help="print the review instead of posting it")
    args = parser.parse_args(argv)

    settings = Settings.from_env(
        repo=args.repo, pr_number=args.pr, provider=args.provider, dry_run=args.dry_run or None
    )
    if not settings.repo or not settings.pr_number:
        parser.error("repository and PR number are required (--repo/--pr or REPO/PR_NUMBER)")

    try:
        result = run_review(settings)
    except HTTPError as exc:
        print(f"GitHub API error: {exc}", file=sys.stderr)
        return 1

    if settings.dry_run:
        print("\n" + result.comment)
    if settings.fail_on_high and result.final_level == "high":
        print("FAIL_ON_HIGH_RISK is set and this PR is high risk: failing the check.", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
