"""Sentinel entry point: detect -> diagnose -> act.

Run normally:   python main.py
                (changes GitHub only if SENTINEL_DRY_RUN=false in .env; default is dry-run)
Replay a past incident through the diagnosis layer, never touching GitHub:
                python main.py --demo
"""

import sys

from actions import DRY_RUN, close_recovered, open_issue_if_new
from checkers import run_all_checks
from diagnose import diagnose

# A replay of a REAL failure from this project's own history: a dependency-resolution
# conflict that broke a Streamlit Cloud deploy. Used to test diagnosis quality safely.
DEMO_FINDING = {
    "target": "PD-Voice-Screening UI",
    "kind": "deploy_failed",
    "summary": "Deploy failed during dependency installation (replayed past incident)",
    "details": {
        "logs": (
            "ERROR: Cannot install -r requirements.txt (line 120) and protobuf==7.36.1 "
            "because these package versions have conflicting dependencies.\n"
            "The conflict is caused by:\n"
            "    The user requested protobuf==7.36.1\n"
            "    googleapis-common-protos 1.75.2 depends on protobuf<8.0.0 and >=6.33.5\n"
            "    onnx 1.22.0 depends on protobuf>=4.25.1\n"
            "    onnxruntime 1.19.2 depends on protobuf\n"
            "    opentelemetry-proto 1.44.0 depends on protobuf<8.0 and >=5.0\n"
            "    streamlit 1.40.1 depends on protobuf<6 and >=3.20\n"
            "ERROR: ResolutionImpossible\n"
            "Error during processing dependencies! Please fix the error and push an update."
        )
    },
}

# Findings that mean "a check could not run", which says nothing about target health.
INCONCLUSIVE_KINDS = {"checker_error", "config_error"}


def report(finding: dict) -> dict:
    print(f"- [{finding['kind']}] {finding['summary']}")
    result = diagnose(finding)
    print(f"    root cause     : {result['root_cause']}")
    print(f"    confidence     : {result['confidence']}")
    print(f"    fix type       : {result['fix_type']}")
    print(f"    suggested fix  : {result['suggested_fix']}")
    print(f"    evidence       : {result['evidence']}")
    if result["evidence_note"]:
        print(f"    note           : {result['evidence_note']}")
    return result


def main() -> None:
    demo = "--demo" in sys.argv
    dry_run = DRY_RUN or demo

    if demo:
        print("Sentinel (demo): replaying a past incident through diagnosis...\n")
        findings = [DEMO_FINDING]
    else:
        print("Sentinel: running health checks...\n")
        findings = run_all_checks()

    if dry_run:
        print("(dry-run: no GitHub changes will be made)\n")

    if not findings:
        print("All targets healthy.")
    else:
        print(f"Found {len(findings)} issue(s):\n")
        for finding in findings:
            result = report(finding)
            open_issue_if_new(finding, result, dry_run=dry_run)
            print()

    if demo:
        return

    # Only auto-close when every check actually ran; an errored check proves nothing.
    if any(f["kind"] in INCONCLUSIVE_KINDS for f in findings):
        print("Skipping auto-close: at least one check could not run.")
    else:
        close_recovered(findings, dry_run=dry_run)


if __name__ == "__main__":
    main()
