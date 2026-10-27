"""Deterministic, rule-based risk signals computed from a PR's changed files.

These run before (and independently of) the LLM, so every PR gets a baseline
risk assessment even if the AI call fails, and the AI cannot talk the bot out
of an obvious red flag such as a hardcoded secret.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

LEVELS = ["low", "medium", "high"]

# (regex on the file path, human-readable category)
SENSITIVE_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"(^|/)\.github/workflows/"), "CI/CD workflow"),
    (re.compile(r"(auth|login|session|jwt|oauth|password|token|crypto|security|permission)", re.I),
     "authentication / security"),
    (re.compile(r"(^|/)migrations?/|\.sql$|(^|/)schema\.", re.I), "database schema / migration"),
    (re.compile(r"(payment|billing|checkout|invoice|wallet)", re.I), "payments / billing"),
    (re.compile(r"(^|/)(Dockerfile|docker-compose[^/]*\.ya?ml|Procfile)$|(^|/)(k8s|helm|terraform)/", re.I),
     "deployment / infrastructure"),
    (re.compile(r"(^|/)(\.env[^/]*|settings\.py|config\.(py|js|ts|ya?ml|json))$", re.I), "configuration"),
    (re.compile(r"(^|/)(requirements[^/]*\.txt|pyproject\.toml|package\.json|go\.mod|pom\.xml|build\.gradle)$"),
     "dependencies"),
]

TEST_PATTERN = re.compile(
    r"(^|/)(tests?|__tests__|spec)/|(^|/)test_[^/]+\.py$|_test\.(py|go)$|\.(test|spec)\.[jt]sx?$"
)

CODE_EXTENSIONS = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".java", ".go", ".rb", ".php", ".cs", ".c", ".h",
    ".cpp", ".hpp", ".rs", ".kt", ".swift", ".scala", ".sql", ".dart", ".vue", ".sh",
}

DOC_EXTENSIONS = {".md", ".rst", ".txt", ".adoc"}

LOCKFILES = {
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock", "Pipfile.lock",
    "Cargo.lock", "go.sum", "composer.lock", "Gemfile.lock",
}

SECRET_PATTERNS: list[re.Pattern] = [
    re.compile(r"AKIA[0-9A-Z]{16}"),  # AWS access key id
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\b(ghp|gho|ghs|github_pat)_[A-Za-z0-9_]{20,}"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{30,}"),
    re.compile(
        r"(secret|passwd|password|api[_-]?key|access[_-]?key|token|private[_-]?key)\w*\s*[:=]\s*[\"'][^\"'\s]{6,}[\"']",
        re.I,
    ),
]


@dataclass
class FileChange:
    filename: str
    status: str = "modified"
    additions: int = 0
    deletions: int = 0
    patch: str | None = None

    @property
    def churn(self) -> int:
        return self.additions + self.deletions

    @property
    def basename(self) -> str:
        return self.filename.rsplit("/", 1)[-1]

    @property
    def extension(self) -> str:
        name = self.basename
        return name[name.rfind("."):].lower() if "." in name else ""


@dataclass
class Signals:
    files_changed: int = 0
    additions: int = 0
    deletions: int = 0
    sensitive: dict[str, list[str]] = field(default_factory=dict)
    code_files: list[str] = field(default_factory=list)
    test_files: list[str] = field(default_factory=list)
    possible_secrets: list[str] = field(default_factory=list)
    skipped_files: list[str] = field(default_factory=list)
    docs_only: bool = False
    score: int = 0
    level: str = "low"
    reasons: list[str] = field(default_factory=list)

    @property
    def churn(self) -> int:
        return self.additions + self.deletions


def files_from_api(raw_files: list[dict]) -> list[FileChange]:
    """Convert GitHub's `GET /pulls/{n}/files` items into FileChange objects."""
    return [
        FileChange(
            filename=f.get("filename", ""),
            status=f.get("status", "modified"),
            additions=int(f.get("additions") or 0),
            deletions=int(f.get("deletions") or 0),
            patch=f.get("patch"),
        )
        for f in raw_files
    ]


def is_test_file(path: str) -> bool:
    return bool(TEST_PATTERN.search(path))


def is_lockfile(change: FileChange) -> bool:
    return change.basename in LOCKFILES


def added_lines(patch: str | None) -> list[tuple[int, str]]:
    """Return (new_line_number, text) for every added line in a unified diff hunk."""
    if not patch:
        return []
    result: list[tuple[int, str]] = []
    new_line = 0
    for line in patch.splitlines():
        if line.startswith("@@"):
            match = re.search(r"\+(\d+)", line)
            new_line = int(match.group(1)) if match else 0
        elif line.startswith("+") and not line.startswith("+++"):
            result.append((new_line, line[1:]))
            new_line += 1
        elif line.startswith("-") and not line.startswith("---"):
            continue
        elif line.startswith("\\"):
            continue  # "\ No newline at end of file"
        else:
            new_line += 1
    return result


def find_possible_secrets(change: FileChange) -> list[str]:
    hits = []
    for line_no, text in added_lines(change.patch):
        if any(p.search(text) for p in SECRET_PATTERNS):
            hits.append(f"{change.filename}:{line_no}")
    return hits


def compute_signals(files: list[FileChange]) -> Signals:
    s = Signals()
    s.files_changed = len(files)
    s.additions = sum(f.additions for f in files)
    s.deletions = sum(f.deletions for f in files)

    for f in files:
        if is_lockfile(f) or f.patch is None:
            s.skipped_files.append(f.filename)
        if is_test_file(f.filename):
            s.test_files.append(f.filename)
        elif f.extension in CODE_EXTENSIONS:
            s.code_files.append(f.filename)
        for pattern, category in SENSITIVE_PATTERNS:
            if pattern.search(f.filename) and not is_test_file(f.filename):
                s.sensitive.setdefault(category, []).append(f.filename)
        if not is_lockfile(f):
            s.possible_secrets.extend(find_possible_secrets(f))

    s.docs_only = bool(files) and all(
        f.extension in DOC_EXTENSIONS or f.filename.startswith("docs/") for f in files
    )

    score, reasons = 0, []

    churn = sum(f.churn for f in files if not is_lockfile(f))  # generated lockfiles don't add review risk
    if churn >= 500:
        score += 30
        reasons.append(f"large change ({churn} lines changed)")
    elif churn >= 200:
        score += 20
        reasons.append(f"medium-sized change ({churn} lines changed)")
    elif churn >= 50:
        score += 10

    if s.files_changed > 25:
        score += 15
        reasons.append(f"touches many files ({s.files_changed})")
    elif s.files_changed > 10:
        score += 10
        reasons.append(f"touches {s.files_changed} files")

    if s.sensitive:
        score += min(15 * len(s.sensitive), 30)
        reasons.append("touches sensitive areas: " + ", ".join(sorted(s.sensitive)))

    code_churn = sum(f.churn for f in files if f.filename in s.code_files)
    if s.code_files and not s.test_files and code_churn > 20:
        score += 15
        reasons.append("code changed without any test changes")

    if s.possible_secrets:
        score += 40
        reasons.append(f"possible hardcoded secret(s) in {len(s.possible_secrets)} line(s)")

    if s.docs_only:
        score = 0
        reasons = ["documentation-only change"]

    s.score = min(score, 100)
    s.level = "high" if s.score >= 50 else "medium" if s.score >= 25 else "low"
    if s.possible_secrets:
        s.level = "high"
    s.reasons = reasons
    return s
