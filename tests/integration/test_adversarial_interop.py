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
    legacy shape). M6 Tier B.1: invocation also passes
    `--beril-root "$BERIL_ROOT"` (without it, beril-adversarial
    resolves BERIL_ROOT from its own pipx install path and fails)."""
    text = _ORCHESTRATOR.read_text(encoding="utf-8")
    # Per M6 Tier B.1, the invocation spans multiple lines (continuation
    # backslashes for readability). Assert all three required pieces
    # appear in the same stage function:
    assert "beril-adversarial review --type presentation" in text, (
        "orchestrator missing the v0.6.0+ review subcommand exec")
    assert '"$OUTDIR"' in text, (
        "orchestrator missing $OUTDIR positional draft_dir arg")
    # M6 Tier B.1: --beril-root must be passed explicitly to
    # beril-adversarial. Without it, the subprocess resolves
    # BERIL_ROOT from its own pipx install path and exits 1 with
    # "does not contain .claude/skills/" — caught live in M6 Tier B.
    assert '--beril-root "$BERIL_ROOT"' in text, (
        "orchestrator missing explicit --beril-root \"$BERIL_ROOT\" "
        "for beril-adversarial (M6 Tier B.1; mirrors the cascade "
        "Tier-3 fix from M4b Tier E round 2 / D-058)")


def test_orchestrator_handles_adversarial_not_installed_gracefully():
    """When `beril-adversarial` isn't on PATH, the stage skips with a
    helpful message rather than crashing. The skip path matters for
    fresh installs / hub deployments where adversarial may not yet be
    pipx-installed."""
    text = _ORCHESTRATOR.read_text(encoding="utf-8")
    assert 'command -v beril-adversarial' in text, (
        "stage_adversarial_review missing the not-installed-skip guard"
    )


def test_orchestrator_branches_on_adversarial_exit_code():
    """M6 Tier B.2 (per adversarial v0.7.0.7 + v0.7.0.8 exit-code
    contract): stage_adversarial_review MUST capture the exit code and
    branch explicitly on rc=4 (not just `|| {warn}` catch-all).

    Per CONTRACT.md:
      rc=0 → JSON consumer-safe
      rc=2 → auto-repaired but still consumer-safe
      rc=3 → config error
      rc=4 → JSON NOT consumer-safe (unparseable OR schema-invalid);
              .md is intact, do not parse the .json
      other → unexpected failure

    The adversarial team explicitly corrected an earlier "messaging-only"
    framing — catching rc=4 with a logging-only catch-all is NOT
    correctness-safe. A schema-invalid file PARSES; a downstream
    `if [[ -f $JSON ]]; then load_it` gate would see it present and
    revise_loop would iterate on broken findings. Paper-writer hit
    this; ship the fix per their v1.0.1 pattern (quarantine the .json).
    """
    text = _ORCHESTRATOR.read_text(encoding="utf-8")
    # Must capture exit code, not just truthy-check
    assert "local rc=$?" in text, (
        "stage_adversarial_review must capture beril-adversarial's exit "
        "code into a local var (M6 Tier B.2; was `|| { return 1 }` "
        "which collapses rc=4 with rc=1/2/3)")
    # Must branch on rc=4 specifically
    assert "case " in text and '"$rc"' in text, (
        "stage_adversarial_review must use `case $rc in` to branch on "
        "exit code per v0.7.0.7+v0.7.0.8 contract")
    assert "    4)" in text or "  4)" in text, (
        "stage_adversarial_review missing explicit rc=4 branch")
    # Must quarantine the .json on rc=4 (paper-writer v1.0.1 pattern)
    assert "quarantined-rc4" in text, (
        "stage_adversarial_review missing .json quarantine on rc=4. "
        "Without quarantine, the downstream file-existence check sees "
        "the schema-invalid file as present and revise_loop iterates "
        "on broken findings (paper-writer v1.0.1 fix pattern)")
    # Must NOT quarantine the .md (always intact per contract)
    assert "review_md" in text, (
        "stage_adversarial_review must preserve the .md (always intact "
        "regardless of rc per CONTRACT.md)")
    # Must distinguish rc=2 from rc=0 in messaging (audit-trail value)
    assert "auto-repaired" in text.lower() or "rc=2" in text, (
        "stage_adversarial_review missing rc=2 distinct messaging "
        "(v0.7.0.7 auto-repair audit signal)")


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


def _resolve_beril_root() -> Path | None:
    """Find a BERIL_ROOT for the live test. Resolution order:

      1. $BERIL_ROOT env var (explicit operator override)
      2. <workspace_root>/spike/beril-extended (the local BERIL fork
         where atlas + adversarial + presentation-maker have all run
         their install-skill commands during dev)
      3. None — caller skips the test
    """
    env_root = os.environ.get("BERIL_ROOT")
    if env_root and Path(env_root).is_dir():
        return Path(env_root)
    # Walk up from this test file to find the workspace root, then
    # check spike/beril-extended.
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "spike" / "beril-extended"
        if candidate.is_dir() and (candidate / ".claude" / "skills").is_dir():
            return candidate
        # Stop if we've walked past the workspace
        if parent.name == "research-coscientist-dev":
            break
    return None


def _resolve_real_draft(beril_root: Path) -> Path | None:
    """Find a real draft for the live test. Adversarial v0.5.2+ detects
    v0.3.1 layout and requires the complete fragment suite
    (qa_anticipated.json, cross_tenant.json, S1_slides.json, etc.) —
    reproducing that in synthetic fixture would mean reimplementing the
    orchestrator. Use a real draft instead.

    M4a Tier D1 (Adam 2026-05-23): EXPLICIT operator opt-in only. The
    pre-Tier-D auto-discovery walked <BERIL_ROOT>/projects/ looking for
    any draft with a full fragment suite; if one happened to exist
    (which is normal mid-development), the test fired a live ~$0.50
    LLM call during routine `pytest tests/`. Stalled Adam's M3 commit-
    gate run for 3.5 minutes.

    Returns the draft pointed at by $TEST_DRAFT_DIR, or None (the
    caller skips). No discovery walk.
    """
    explicit = os.environ.get("TEST_DRAFT_DIR")
    if explicit and Path(explicit).is_dir():
        return Path(explicit)
    return None


@pytest.mark.integration
def test_live_adversarial_review_emits_v3_schema(tmp_path):
    """Live integration: invoke real `beril-adversarial review --type
    presentation` against a real draft, assert (a) exits 0, (b) output
    file exists, (c) JSON parses, (d) schema_version is v3.

    Costs ~$0.50/run on live LLM (Sonnet review). M4a Tier D1
    (Adam 2026-05-23): the @pytest.mark.integration marker alone is
    insufficient gating — pyproject's addopts doesn't deselect
    integration tests, so `pytest tests/` collected this test, and the
    pre-D auto-discovery walk picked up a real draft and fired the
    live LLM call (stalled the M3 commit-gate run 3.5 min). Now gated
    by TWO explicit opt-ins; both must be set:

      BERIL_PRESENTATION_MAKER_RUN_LIVE=1   ← "yes, I want live LLM
                                              calls in this pytest run"
      TEST_DRAFT_DIR=/path/to/real/draft    ← which draft to review

    The first guard makes it impossible to fire a live call
    accidentally — `TEST_DRAFT_DIR` may legitimately be set for
    unrelated reasons (e.g., an IDE leftover). The second guard
    replaces the auto-discovery walk.

    Requires:
    - beril-adversarial CLI installed via pipx
    - BERIL_ROOT resolvable ($BERIL_ROOT or spike/beril-extended/)
    - CBORG_API_KEY in env (or in BERIL_ROOT/.env)

    Pointing at a real draft (vs. synthetic fixture) avoids
    reimplementing the orchestrator's fragment suite — the producer
    requires every per-substory + qa_anticipated + cross_tenant
    fragment once it detects v0.3.1+ layout.
    """
    # Tier D1: hard gate on the explicit opt-in env var. The marker
    # alone doesn't keep `pytest tests/` from collecting + running
    # this test (addopts has no -m filter).
    if os.environ.get("BERIL_PRESENTATION_MAKER_RUN_LIVE") != "1":
        pytest.skip(
            "live LLM test gated behind BERIL_PRESENTATION_MAKER_RUN_LIVE=1 "
            "(M4a Tier D1 — prevents accidental ~$0.50 spend on routine "
            "pytest runs)"
        )
    if not _adversarial_cli_is_installed():
        pytest.skip("beril-adversarial CLI not installed")
    if not _adversarial_cli_has_review_subcommand():
        pytest.skip("beril-adversarial < v0.6.0 (no `review` subcommand)")
    beril_root = _resolve_beril_root()
    if beril_root is None:
        pytest.skip(
            "BERIL_ROOT not resolvable; set $BERIL_ROOT or ensure "
            "spike/beril-extended/.claude/skills/ exists"
        )
    real_draft = _resolve_real_draft(beril_root)
    if real_draft is None:
        pytest.skip(
            "Set $TEST_DRAFT_DIR to a real v0.3.1+ draft path "
            "(M4a Tier D1: explicit operator opt-in only; the prior "
            "auto-discovery walk was removed to prevent accidental "
            "live LLM spend)."
        )

    # Snapshot the real draft's existing audit/adversarial_review.{md,json}
    # if present, so the test doesn't clobber prior reviews. Restore
    # at end whether the test passes or fails.
    audit_dir = real_draft / "audit"
    review_json_path = audit_dir / "adversarial_review.json"
    review_md_path = audit_dir / "adversarial_review.md"
    backup_json = tmp_path / "adversarial_review.json.bak"
    backup_md = tmp_path / "adversarial_review.md.bak"
    had_prior_json = review_json_path.is_file()
    had_prior_md = review_md_path.is_file()
    if had_prior_json:
        backup_json.write_bytes(review_json_path.read_bytes())
    if had_prior_md:
        backup_md.write_bytes(review_md_path.read_bytes())

    try:
        # Invoke the producer. Pass --beril-root explicitly so the
        # adversarial CLI can locate its installed .claude/skills/ —
        # otherwise it walks the script location (in pipx venv) and fails.
        env = os.environ.copy()
        result = subprocess.run(
            ["beril-adversarial", "review",
             "--type", "presentation",
             "--beril-root", str(beril_root),
             str(real_draft)],
            capture_output=True, text=True, timeout=600, env=env,
        )

        # (a) exits 0
        assert result.returncode == 0, (
            f"beril-adversarial review exited {result.returncode}\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )

        # (b) output file exists
        assert review_json_path.is_file(), (
            f"expected output {review_json_path} not produced; "
            f"audit/ contains: {list(audit_dir.iterdir())}"
        )

        # (c) JSON parses
        review = json.loads(review_json_path.read_text(encoding="utf-8"))
        assert isinstance(review, dict), "review JSON is not a dict"
        assert "findings" in review, "review missing findings array"

        # (d) schema_version is v3 (post-v0.7.0)
        schema_version = review.get("schema_version", "")
        assert schema_version == "adversarial-review-presentation.v3", (
            f"expected schema_version "
            f"'adversarial-review-presentation.v3', got "
            f"{schema_version!r}. If v2: producer is on a pre-v0.7.0 "
            f"release; reinstall via "
            f"`pipx install --force git+https://github.com/ArkinLaboratory"
            f"/beril-adversarial-skill.git@v0.7.0.1`."
        )
    finally:
        # Restore prior review files (or remove the new ones).
        if had_prior_json:
            review_json_path.write_bytes(backup_json.read_bytes())
        elif review_json_path.is_file():
            review_json_path.unlink()
        if had_prior_md:
            review_md_path.write_bytes(backup_md.read_bytes())
        elif review_md_path.is_file():
            review_md_path.unlink()
