"""
Action layer: file GitHub issues for findings, never duplicate them, and close
them automatically once the target recovers.

Safety rules:
- Dry-run is the DEFAULT. Nothing touches GitHub unless SENTINEL_DRY_RUN=false.
- The only write actions here are creating/commenting on/closing issues that
  carry the 'sentinel' label. Reversible and low risk by design.
"""

import os

from github import Auth, Github
from github.GithubException import UnknownObjectException

from config import GITHUB_TOKEN, TARGET_REPOS

LABEL = "sentinel"
TITLE_PREFIX = "[Sentinel]"
DEFAULT_REPO = "Baffxy/PD-Voice-Screening"
DRY_RUN = os.getenv("SENTINEL_DRY_RUN", "true").strip().lower() != "false"


def issue_title(finding: dict) -> str:
    return f"{TITLE_PREFIX} {finding['target']}: {finding['kind']}"


def repo_for(finding: dict) -> str:
    return TARGET_REPOS.get(finding["target"], DEFAULT_REPO)


def _client() -> Github:
    if not GITHUB_TOKEN:
        raise RuntimeError("GITHUB_TOKEN is not set in .env")
    return Github(auth=Auth.Token(GITHUB_TOKEN))


def _ensure_label(repo):
    try:
        return repo.get_label(LABEL)
    except UnknownObjectException:
        return repo.create_label(LABEL, "d93f0b", "Opened automatically by Sentinel")


def _body(finding: dict, diagnosis: dict) -> str:
    details = {k: v for k, v in finding["details"].items() if k != "logs"}
    detail_lines = "\n".join(f"- **{k}:** {v}" for k, v in details.items()) or "- (none)"
    note = f"\n> {diagnosis['evidence_note']}" if diagnosis.get("evidence_note") else ""

    return f"""## What Sentinel detected
{finding['summary']}

{detail_lines}

## Diagnosis
- **Root cause:** {diagnosis['root_cause']}
- **Confidence:** {diagnosis['confidence']}
- **Evidence available:** {diagnosis['evidence']}{note}
- **Fix type:** {diagnosis['fix_type']}

## Suggested fix
{diagnosis['suggested_fix']}

---
_Opened automatically by Sentinel. The diagnosis is LLM-generated: treat it as a hypothesis and verify before acting. This issue closes automatically once the target is healthy again._"""


def open_issue_if_new(finding: dict, diagnosis: dict, dry_run: bool = DRY_RUN) -> None:
    title = issue_title(finding)
    repo_name = repo_for(finding)

    if dry_run:
        print(f"    [dry-run] would open issue in {repo_name}: {title}")
        return

    repo = _client().get_repo(repo_name)
    label = _ensure_label(repo)

    for issue in repo.get_issues(state="open", labels=[label]):
        if issue.title == title:
            print(f"    Issue already open, not duplicating: {issue.html_url}")
            return

    issue = repo.create_issue(title=title, body=_body(finding, diagnosis), labels=[label])
    print(f"    Opened issue: {issue.html_url}")


def close_recovered(findings: list, dry_run: bool = DRY_RUN) -> None:
    """Close open Sentinel issues whose target no longer has an active finding."""
    active_titles = {issue_title(f) for f in findings}

    for repo_name in sorted(set(TARGET_REPOS.values())):
        if dry_run:
            print(f"[dry-run] would check {repo_name} for recovered issues to close")
            continue

        repo = _client().get_repo(repo_name)
        label = _ensure_label(repo)
        for issue in repo.get_issues(state="open", labels=[label]):
            if issue.title.startswith(TITLE_PREFIX) and issue.title not in active_titles:
                issue.create_comment(
                    "Sentinel re-checked this target and it is healthy again. Closing automatically."
                )
                issue.edit(state="closed")
                print(f"Closed recovered issue: {issue.html_url}")
