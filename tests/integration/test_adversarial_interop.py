"""Cross-skill smoke for the presentation-maker → beril-adversarial integration.

Per V0_3_3_ARCHITECTURE.md §18 + adversarial team v0.7.0.1 guidance: the
producer (beril-adversarial) cannot enforce that consumers call its CLI
correctly — only the consumer can. This test is the consumer-side smoke
that asserts our orchestrator's adversarial invocation works end-to-end.

Two layers:

1. **Fast unit-level shape check** (always runs). Greps the orchestrator
   bash for the expected `beril-adversarial review --type presentation
   <draft_dir>` invocation shape. Catches the recurring cross-skill
   contract drift pattern (3 strikes in May 2026) cheaply: if anyone
   removes the v0.6.0+ `review` subcommand or breaks the --type / draft
   positional shape, this test fails on the next run.

2. **Marked integration check** (runs only with `pytest -m integration`).
   Subprocess-invokes a real `beril-adversarial review --type presentation`
   against a synthetic draft. Asserts (a) exits 0, (b) output file exists,
   (c) JSON parses, (d) schema_version matches v3 (per v0.7.0.1 contract).
   Skipped by default — costs ~$0.50/run on live LLM.

Reference: feedback_cross_skill_contract_drift.md (memory) + paper-writer's
test_paper_writer_interop.py (which solves the producer-side; this is the
consumer-side counterpart).
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_ORCHESTRATOR = (
    _REPO_ROOT / "src" / "beril_presentation_maker"
    / "skill" / "tools" / "presentation_maker.sh"
)


# ---------------------------------------------------------------------------
# Layer 1: invocation-shape unit check (always runs; no LLM cost)
# ---------------------------------------------------------------------------

def test_orchestrator_invokes_adversarial_review_subcommand_v0_6_plus():
    """The stage_adversarial_review function must invoke the v0.6.0+
    `beril-adversarial review --type presentation` shape, not the
    pre-v0.6 `beril-adversarial --type presentation`.

    Recurring failure mode: paper-writer's draft_9 incident (memory
    feedback_cross_skill_contract_drift.md) shipped a v0.6+ adversarial
    against a v0.5 invocation shape and captured argparse stderr as the
    "review file." This test prevents the same regression here."""
    text = _ORCHESTRATOR.read_text(encoding="utf-8")
    # The orchestrator probes for the `review` subcommand and falls back
    # to a sibling shell script for v0.5.x. Both paths must be present.
    assert "beril-adversarial review --type presentation" in text, (
        "orchestrator missing v0.6.0+ `review` subcommand invocation"
    )
    # The probe must use --help (cheap) to detect the subcommand,
    # not exec a real review.
    assert "beril-adversarial --help" in text, (
        "orchestrator missing --help-based subcommand probe"
    )


def test_orchestrator_passes_outdir_as_draft_dir_positional():
    """The v0.6.0+ CLI takes <draft_dir> as positional after
    `--type presentation`. Confirm we pass `$OUTDIR` (the resolved
    draft directory) and not `$PROJECT_ID` (would be the v0.5
    legacy shape)."""
    text = _ORCHESTRATOR.read_text(encoding="utf-8")
    # Look for the actual exec line shape
    invocation = "beril-adversarial review --type presentation \"$OUTDIR\""
    assert invocation in text, (
        f"orchestrator missing expected invocation:\n  {invocation}\n"
        "Cross-check stage_adversarial_review."
    )


def test_orchestrator_handles_adversarial_not_installed_gracefully():
    """When `beril-adversarial` isn't on PATH, the stage skips with a
    helpful message rather than crashing. The skip path matters for
    fresh installs / hub deployments where adversarial may not yet be
    pipx-installed."""
    text = _ORCHESTRATOR.read_text(encoding="utf-8")
    assert 'command -v beril-adversarial' in text, (
        "stage_adversarial_review missing the not-installed-skip guard"
    )


# ---------------------------------------------------------------------------
# Layer 2: live integration (marker-gated; costs LLM money)
# ---------------------------------------------------------------------------

def _adversarial_cli_is_installed() -> bool:
    """Cheap check: is `beril-adversarial` on PATH?"""
    return shutil.which("beril-adversarial") is not None


def _adversarial_cli_has_review_subcommand() -> bool:
    """Probe: does the installed CLI expose the v0.6.0+ `review`
    subcommand? Mirrors the orchestrator's own probe logic."""
    try:
        result = subprocess.run(
            ["beril-adversarial", "--help"],
            capture_output=True, text=True, timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
    return any(
        line.lstrip().startswith("review")
        for line in (result.stdout + result.stderr).splitlines()
    )


@pytest.mark.integration
def test_live_adversarial_review_emits_v3_schema(tmp_path):
    """Live integration: stand up a minimal draft directory with a
    valid slide_spec.json + REPORT.md, invoke the real
    `beril-adversarial review --type presentation`, and assert (a)
    exits 0, (b) output file exists, (c) JSON parses, (d)
    schema_version is v3.

    This runs only when `pytest -m integration` is explicitly
    requested. Costs ~$0.50/run on live LLM (Sonnet review of a
    minimal deck).
    """
    if not _adversarial_cli_is_installed():
        pytest.skip("beril-adversarial CLI not installed")
    if not _adversarial_cli_has_review_subcommand():
        pytest.skip("beril-adversarial < v0.6.0 (no `review` subcommand)")

    # Build a minimal v0.3.1+ draft layout with the bare-minimum
    # files the adversarial reviewer needs to read.
    draft_dir = tmp_path / "projects" / "synthetic" / "talks" / "draft_1"
    project_dir = tmp_path / "projects" / "synthetic"
    deliverable = draft_dir / "deliverable"
    narrative = draft_dir / "narrative"
    working = draft_dir / "working"
    audit = draft_dir / "audit"
    for d in (deliverable, narrative, working, audit):
        d.mkdir(parents=True)

    (project_dir / "REPORT.md").write_text(
        "# Synthetic Project\n\nMinimal report for adversarial smoke test.\n",
        encoding="utf-8",
    )
    (project_dir / "RESEARCH_PLAN.md").write_text(
        "# Research Plan\n\nMinimal plan.\n",
        encoding="utf-8",
    )
    (narrative / "00_throughline.md").write_text(
        "<!-- chosen: TL1 -->\n<!-- punchline: Synthetic test claim. -->\n"
        "## TL1: Synthetic test\n**Tier:** STRONG\n",
        encoding="utf-8",
    )
    (narrative / "02_substories.md").write_text(
        "### S1 — synthetic substory\n**Punchline:** synthetic.\n",
        encoding="utf-8",
    )
    # Minimal valid slide_spec.json
    (working / "slide_spec.json").write_text(
        json.dumps({
            "schema_version": "1.0",
            "project_id": "synthetic",
            "mode": "talk-30",
            "audience": "peer",
            "tier": "STRONG",
            "throughline": {"id": "TL1", "punchline": "Synthetic.",
                            "tier_evidence": "STRONG"},
            "substories": [{"id": "S1", "punchline": "synthetic",
                            "slide_ids": [1]}],
            "slides": [
                {"id": 1, "position": 0, "substory_id": "S1",
                 "layout": "section_divider",
                 "content": {"punchline": "Synthetic substory.",
                             "substory_number": 1}},
            ],
        }, indent=2),
        encoding="utf-8",
    )

    # Invoke the producer.
    env = os.environ.copy()
    result = subprocess.run(
        ["beril-adversarial", "review",
         "--type", "presentation", str(draft_dir)],
        capture_output=True, text=True, timeout=600, env=env,
    )

    # (a) exits 0
    assert result.returncode == 0, (
        f"beril-adversarial review exited {result.returncode}\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )

    # (b) output file exists
    review_json = audit / "adversarial_review.json"
    assert review_json.is_file(), (
        f"expected output {review_json} not produced; "
        f"audit/ contains: {list(audit.iterdir())}"
    )

    # (c) JSON parses
    review = json.loads(review_json.read_text(encoding="utf-8"))
    assert isinstance(review, dict), "review JSON is not a dict"
    assert "findings" in review, "review missing findings array"

    # (d) schema_version is v3 (post-v0.7.0)
    schema_version = review.get("schema_version", "")
    assert schema_version == "adversarial-review-presentation.v3", (
        f"expected schema_version 'adversarial-review-presentation.v3', "
        f"got {schema_version!r}. If v2: producer is on a pre-v0.7.0 "
        f"release; reinstall via "
        f"`pipx install --force git+https://github.com/ArkinLaboratory"
        f"/beril-adversarial-skill.git@v0.7.0.1`."
    )
