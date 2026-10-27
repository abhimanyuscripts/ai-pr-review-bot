"""Minimal GitHub REST API client for reading a PR and writing the review back."""

from __future__ import annotations

import urllib.parse

from .http import HTTPError, request_json
from .render import MARKER

GITHUB_API = "https://api.github.com"

RISK_LABELS = {
    "low": ("risk: low", "2da44e", "AI PR review: low risk"),
    "medium": ("risk: medium", "d4a72c", "AI PR review: medium risk"),
    "high": ("risk: high", "cf222e", "AI PR review: high risk"),
}


class GitHubClient:
    def __init__(self, repo: str, token: str | None = None, api: str = GITHUB_API):
        self.repo = repo
        self.token = token
        self.api = api.rstrip("/")

    def _call(self, method: str, path: str, payload=None):
        headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return request_json(method, f"{self.api}/repos/{self.repo}{path}", headers=headers, payload=payload)

    def get_pull_request(self, number: int) -> dict:
        return self._call("GET", f"/pulls/{number}")

    def get_files(self, number: int, max_pages: int = 10) -> list[dict]:
        files: list[dict] = []
        for page in range(1, max_pages + 1):
            batch = self._call("GET", f"/pulls/{number}/files?per_page=100&page={page}") or []
            files.extend(batch)
            if len(batch) < 100:
                break
        return files

    def upsert_comment(self, number: int, body: str) -> str:
        """Update the bot's previous review comment on this PR, or create one. Returns 'updated' or 'created'."""
        for page in range(1, 6):
            comments = self._call("GET", f"/issues/{number}/comments?per_page=100&page={page}") or []
            for comment in comments:
                if MARKER in (comment.get("body") or ""):
                    self._call("PATCH", f"/issues/comments/{comment['id']}", {"body": body})
                    return "updated"
            if len(comments) < 100:
                break
        self._call("POST", f"/issues/{number}/comments", {"body": body})
        return "created"

    def set_risk_label(self, number: int, level: str) -> None:
        """Make sure exactly one `risk: …` label is on the PR, creating the labels if needed."""
        name, color, description = RISK_LABELS[level]
        try:
            self._call("POST", "/labels", {"name": name, "color": color, "description": description})
        except HTTPError as exc:
            if exc.status != 422:  # 422 = label already exists
                raise
        for other_level, (other_name, _, _) in RISK_LABELS.items():
            if other_level == level:
                continue
            try:
                self._call("DELETE", f"/issues/{number}/labels/{urllib.parse.quote(other_name)}")
            except HTTPError as exc:
                if exc.status != 404:  # 404 = label wasn't on the PR
                    raise
        self._call("POST", f"/issues/{number}/labels", {"labels": [name]})
