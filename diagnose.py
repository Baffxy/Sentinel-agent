"""
Diagnosis layer: turn a raw finding into a structured root-cause assessment.

Design rule: the LLM only RECOMMENDS. Whether any action is actually allowed is
decided later by code-level rules, never by the model's own 'safe_to_automate' claim.
"""

import json

import requests
from groq import Groq

from config import GROQ_API_KEY, RENDER_API_KEY, RENDER_SERVICE_ID

MODEL = "openai/gpt-oss-120b"
MAX_LOG_CHARS = 6000

ALLOWED_FIX_TYPES = {
    "dependency_pin",
    "config_change",
    "code_change",
    "wait_and_retry",
    "manual_investigation",
}
ALLOWED_CONFIDENCE = {"low", "medium", "high"}

SYSTEM_PROMPT = """You are a careful site reliability engineer diagnosing failures in a small portfolio of deployed apps.

System context:
- PD-Voice-Screening API: FastAPI app in Docker, hosted on Render (free tier, sleeps when idle), logs predictions to a Neon Postgres database via DATABASE_URL.
- Frontends (PD-Voice-Screening UI, MedRAG UI): Streamlit apps on Streamlit Community Cloud.

Rules:
- Base your diagnosis ONLY on the evidence provided. Never invent log lines or causes.
- If the evidence is thin (for example, only an HTTP status with no logs), say so, set confidence to "low", and prefer "wait_and_retry" or "manual_investigation".
- Free-tier cold starts can cause slow first responses; do not call a transient slowdown an outage.

Respond with ONLY a JSON object, no markdown, with exactly these keys:
{
  "root_cause": "one or two sentences",
  "confidence": "low" | "medium" | "high",
  "fix_type": "dependency_pin" | "config_change" | "code_change" | "wait_and_retry" | "manual_investigation",
  "suggested_fix": "concrete next step, specific enough to act on",
  "safe_to_automate": true | false
}"""


def fetch_render_logs(limit: int = 100):
    """Best-effort fetch of recent Render service logs. Returns (text, error)."""
    headers = {"Authorization": f"Bearer {RENDER_API_KEY}", "Accept": "application/json"}
    try:
        service = requests.get(
            f"https://api.render.com/v1/services/{RENDER_SERVICE_ID}", headers=headers, timeout=30
        )
        service.raise_for_status()
        owner_id = service.json().get("ownerId")

        response = requests.get(
            "https://api.render.com/v1/logs",
            headers=headers,
            params={
                "ownerId": owner_id,
                "resource": RENDER_SERVICE_ID,
                "limit": limit,
                "direction": "backward",
            },
            timeout=30,
        )
        response.raise_for_status()
        lines = [entry.get("message", "") for entry in response.json().get("logs", [])]
        text = "\n".join(reversed(lines))  # 'backward' returns newest first
        return text[-MAX_LOG_CHARS:], None
    except Exception as exc:  # noqa: BLE001 - any failure here must degrade gracefully
        return None, f"{type(exc).__name__}: {exc}"


def gather_evidence(finding: dict):
    """Return (evidence_text, evidence_level, note)."""
    details = dict(finding.get("details", {}))
    logs = details.pop("logs", None)
    note = ""

    if logs is None and finding["kind"] == "deploy_failed":
        logs, error = fetch_render_logs()
        if error:
            note = f"Render log fetch failed ({error}); diagnosing from deploy metadata only."

    parts = [f"Target: {finding['target']}", f"Problem: {finding['summary']}", f"Details: {json.dumps(details, default=str)}"]
    if logs:
        parts.append(f"Logs (most recent, truncated):\n{logs[-MAX_LOG_CHARS:]}")
        level = "logs"
    else:
        level = "metadata_only"
    return "\n\n".join(parts), level, note


def _safe_fallback(reason: str, level: str, note: str) -> dict:
    return {
        "root_cause": f"Automatic diagnosis was inconclusive ({reason}).",
        "confidence": "low",
        "fix_type": "manual_investigation",
        "suggested_fix": "Review the target manually; the agent could not produce a trustworthy diagnosis.",
        "safe_to_automate": False,
        "evidence": level,
        "evidence_note": note,
    }


def _parse(raw: str, level: str, note: str) -> dict:
    try:
        start, end = raw.index("{"), raw.rindex("}") + 1
        data = json.loads(raw[start:end])
        result = {
            "root_cause": str(data["root_cause"]),
            "confidence": data["confidence"] if data["confidence"] in ALLOWED_CONFIDENCE else "low",
            "fix_type": data["fix_type"] if data["fix_type"] in ALLOWED_FIX_TYPES else "manual_investigation",
            "suggested_fix": str(data["suggested_fix"]),
            "safe_to_automate": bool(data.get("safe_to_automate", False)),
            "evidence": level,
            "evidence_note": note,
        }
        return result
    except (ValueError, KeyError, TypeError, json.JSONDecodeError):
        return _safe_fallback("model output was not valid JSON", level, note)


def diagnose(finding: dict) -> dict:
    evidence, level, note = gather_evidence(finding)
    try:
        client = Groq(api_key=GROQ_API_KEY)
        response = client.chat.completions.create(
            model=MODEL,
            temperature=0,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": evidence},
            ],
        )
        return _parse(response.choices[0].message.content or "", level, note)
    except Exception as exc:  # noqa: BLE001
        return _safe_fallback(f"LLM call failed: {type(exc).__name__}", level, note)
