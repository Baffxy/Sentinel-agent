"""
Detection layer: each check returns None when healthy, or a 'finding' dict
describing what's wrong. Findings are what the diagnosis/action layers consume.
"""

import time

import requests

from config import HTTP_TARGETS, RENDER_API_KEY, RENDER_SERVICE_ID

# Render deploy states that mean "this deploy failed".
FAILED_STATUSES = {"build_failed", "update_failed", "pre_deploy_failed"}


def check_http(name: str, url: str, timeout: int = 60, retries: int = 1):
    """
    Return None if the URL responds with a non-error status, else a finding.

    The timeout is deliberately generous and there's one retry: free-tier hosts
    sleep when idle, and a 30-50s cold start must not be reported as an outage.
    """
    last_error = None
    for attempt in range(retries + 1):
        try:
            response = requests.get(url, timeout=timeout)
            if response.status_code < 400:
                return None
            last_error = f"HTTP {response.status_code}"
        except requests.RequestException as exc:
            last_error = f"{type(exc).__name__}: {exc}"
        if attempt < retries:
            time.sleep(5)

    return {
        "target": name,
        "kind": "http_down",
        "summary": f"{name} is not responding ({last_error})",
        "details": {"url": url, "error": last_error},
    }


def check_render_deploys():
    """
    Look at the most recent Render deploy for the configured service.
    Only the latest deploy matters: an older failure followed by a successful
    deploy is already resolved and shouldn't raise an alert.
    """
    if not RENDER_API_KEY or not RENDER_SERVICE_ID:
        return {
            "target": "Render",
            "kind": "config_error",
            "summary": "RENDER_API_KEY or RENDER_SERVICE_ID is not set",
            "details": {},
        }

    response = requests.get(
        f"https://api.render.com/v1/services/{RENDER_SERVICE_ID}/deploys",
        headers={"Authorization": f"Bearer {RENDER_API_KEY}", "Accept": "application/json"},
        params={"limit": 1},
        timeout=30,
    )
    response.raise_for_status()
    items = response.json()
    if not items:
        return None

    # The API wraps each deploy as {"deploy": {...}, "cursor": "..."}; handle both shapes.
    deploy = items[0].get("deploy", items[0])
    status = deploy.get("status")

    if status not in FAILED_STATUSES:
        return None

    commit = deploy.get("commit") or {}
    return {
        "target": "PD-Voice-Screening API (Render)",
        "kind": "deploy_failed",
        "summary": f"Latest Render deploy ended in '{status}'",
        "details": {
            "deploy_id": deploy.get("id"),
            "status": status,
            "commit_id": commit.get("id"),
            "commit_message": commit.get("message"),
            "finished_at": deploy.get("finishedAt"),
        },
    }


def run_all_checks():
    """Run every check and return the list of findings (empty list = all healthy)."""
    findings = []

    for name, url in HTTP_TARGETS.items():
        finding = check_http(name, url)
        if finding:
            findings.append(finding)

    try:
        deploy_finding = check_render_deploys()
        if deploy_finding:
            findings.append(deploy_finding)
    except requests.RequestException as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        reason = f"HTTP {status}" if status else type(exc).__name__
        findings.append(
            {
                "target": "Render",
                "kind": "checker_error",
                "summary": f"Could not query the Render API: {exc}",
                "details": {},
            }
        )

    return findings
