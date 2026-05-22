"""Unit tests for tools/phase0_reuse.py.

Authored for presentation-maker v0.4 M1 Tier C (2026-05-14) per
M1_PUNCH_LIST.md Tier C C2 test matrix.

The 14-test matrix from the punch list, plus 3 error/exit-code-contract
tests (#15 claim_inventory precondition, #16 sub-tool failure → exit 2,
#17 main bad --project-dir → exit 1) — the exit-code contract is
load-bearing and was otherwise untested. Plus 1 regression test added
after the M1 Tier C code review (test_decide_no_op_skipped_when_prior_stamp_is_error
— Blocker #1: an `error` stamp must not poison the no-op fast-path).

All tests use tmp_path for synthetic project + talk-draft scaffolding.
The vendored-tool invocations (extract_methods.main / extract_claims.main)
are mocked via unittest.mock.patch — no live `claude -p`.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from beril_presentation_maker.skill.tools import phase0_reuse as pr
from beril_presentation_maker.skill.tools.draft_paths import DraftPaths


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

def _make_project(
    tmp_path: Path,
    *,
    name: str = "synthetic_project",
    with_report: bool = True,
    with_research_plan: bool = False,
    notebooks: tuple[str, ...] = ("NB01.ipynb",),
) -> Path:
    """Create a synthetic project dir with notebooks + REPORT.md."""
    proj = tmp_path / name
    (proj / "notebooks").mkdir(parents=True, exist_ok=True)
    for nb in notebooks:
        (proj / "notebooks" / nb).write_text(
            '{"cells": [], "metadata": {}, "nbformat": 4, "nbformat_minor": 5}',
            encoding="utf-8",
        )
    if with_report:
        (proj / "REPORT.md").write_text(
            "# Report\n\nx = 88.2%.\n", encoding="utf-8"
        )
    if with_research_plan:
        (proj / "RESEARCH_PLAN.md").write_text("# Plan\n", encoding="utf-8")
    return proj


def _make_paper_draft(
    project_dir: Path, draft_n: int, artifact_filename: str, content: str
) -> Path:
    """Create projects/<id>/papers/draft_<N>/<artifact_filename>."""
    d = project_dir / "papers" / f"draft_{draft_n}"
    d.mkdir(parents=True, exist_ok=True)
    path = d / artifact_filename
    path.write_text(content, encoding="utf-8")
    return path


def _make_talk_draft(tmp_path: Path, name: str = "draft_1") -> Path:
    """Create talks/<name>/ (decide_and_act's init_layout fills the rest)."""
    talk = tmp_path / "talks" / name
    talk.mkdir(parents=True, exist_ok=True)
    return talk


def _write_stamp(
    audit_dir: Path,
    artifact: str,
    inputs_hashed: str,
    *,
    tool: str = "phase0_reuse",
    decision: str = "originate",
) -> None:
    """Append a synthetic record to <audit_dir>/phase0.jsonl."""
    audit_dir.mkdir(parents=True, exist_ok=True)
    rec = {
        "tool": tool,
        "artifact": artifact,
        "inputs_hashed": inputs_hashed,
        "decision": decision,
        "timestamp": "2026-05-14T00:00:00Z",
    }
    with (audit_dir / "phase0.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")


# ---------------------------------------------------------------------------
# 1-3 — compute_input_hash
# ---------------------------------------------------------------------------

def test_compute_input_hash_methods_stable(tmp_path):
    """Hash for methods_provenance inputs is deterministic across calls."""
    proj = _make_project(tmp_path)
    tp = DraftPaths.from_draft_dir(_make_talk_draft(tmp_path))
    h1 = pr.compute_input_hash("methods_provenance", proj, tp)
    h2 = pr.compute_input_hash("methods_provenance", proj, tp)
    assert h1 == h2
    assert len(h1) == 64  # sha256 hex digest


def test_compute_input_hash_methods_changes_on_notebook_edit(tmp_path):
    """Editing one notebook cell changes the methods_provenance hash."""
    proj = _make_project(tmp_path)
    tp = DraftPaths.from_draft_dir(_make_talk_draft(tmp_path))
    h1 = pr.compute_input_hash("methods_provenance", proj, tp)
    (proj / "notebooks" / "NB01.ipynb").write_text(
        '{"cells": ["edited"]}', encoding="utf-8"
    )
    h2 = pr.compute_input_hash("methods_provenance", proj, tp)
    assert h1 != h2


def test_compute_input_hash_claim_includes_methods_dependency(tmp_path):
    """claim_inventory hash tracks REPORT.md + methods_provenance.md, NOT
    notebooks directly (notebook drift reaches it only through a
    regenerated methods_provenance.md)."""
    proj = _make_project(tmp_path)
    tp = DraftPaths.from_draft_dir(_make_talk_draft(tmp_path))
    tp.init_layout()
    tp.methods_provenance_phase0.write_text("methods v1\n", encoding="utf-8")
    h1 = pr.compute_input_hash("claim_inventory", proj, tp)

    # editing a notebook directly does NOT move the claim hash
    (proj / "notebooks" / "NB01.ipynb").write_text(
        '{"cells": ["edited"]}', encoding="utf-8"
    )
    h2 = pr.compute_input_hash("claim_inventory", proj, tp)
    assert h2 == h1

    # editing methods_provenance.md DOES move it
    tp.methods_provenance_phase0.write_text("methods v2\n", encoding="utf-8")
    h3 = pr.compute_input_hash("claim_inventory", proj, tp)
    assert h3 != h1

    # editing REPORT.md also moves it
    (proj / "REPORT.md").write_text("# Report\n\nx = 99.9%.\n", encoding="utf-8")
    h4 = pr.compute_input_hash("claim_inventory", proj, tp)
    assert h4 != h3


# ---------------------------------------------------------------------------
# 4-6 — find_paper_writer_artifact
# ---------------------------------------------------------------------------

def test_find_paper_writer_artifact_picks_most_recent(tmp_path):
    """Two paper drafts both carry the artifact → return the highest-N path."""
    proj = _make_project(tmp_path)
    _make_paper_draft(proj, 1, "methods_provenance.md", "draft 1 methods\n")
    p2 = _make_paper_draft(proj, 2, "methods_provenance.md", "draft 2 methods\n")
    assert pr.find_paper_writer_artifact(proj, "methods_provenance") == p2


def test_find_paper_writer_artifact_skips_missing(tmp_path):
    """A newer draft dir without the artifact is skipped; fall back to draft_2."""
    proj = _make_project(tmp_path)
    _make_paper_draft(proj, 1, "methods_provenance.md", "d1\n")
    p2 = _make_paper_draft(proj, 2, "methods_provenance.md", "d2\n")
    (proj / "papers" / "draft_3").mkdir(parents=True, exist_ok=True)  # no artifact
    assert pr.find_paper_writer_artifact(proj, "methods_provenance") == p2


def test_find_paper_writer_artifact_none_when_no_drafts(tmp_path):
    """No papers/ dir at all → None for both artifacts."""
    proj = _make_project(tmp_path)
    assert pr.find_paper_writer_artifact(proj, "methods_provenance") is None
    assert pr.find_paper_writer_artifact(proj, "claim_inventory") is None


# ---------------------------------------------------------------------------
# 7-9 — decide_and_act: reuse / originate / force-originate
# ---------------------------------------------------------------------------

def test_decide_reuse_when_paper_artifact_present(tmp_path):
    """Paper-writer artifact present → decision=reuse, byte-equal copy lands
    at working/00_phase0/, audit record fields correct."""
    proj = _make_project(tmp_path)
    src = _make_paper_draft(
        proj, 1, "methods_provenance.md", "paper-writer methods\n"
    )
    talk = _make_talk_draft(tmp_path)

    record, rc = pr.decide_and_act("methods_provenance", proj, talk)

    assert rc == 0
    assert record["decision"] == "reuse"
    assert record["rationale"] == "paper_artifact_present"
    assert record["source_path"] == str(src)
    assert record["cost_usd"] == 0.0
    assert record["tool"] == "phase0_reuse"
    tp = DraftPaths.from_draft_dir(talk)
    assert tp.methods_provenance_phase0.is_file()
    assert tp.methods_provenance_phase0.read_text() == "paper-writer methods\n"


def test_decide_originate_when_paper_artifact_absent(tmp_path):
    """No paper-writer artifact → decision=originate, vendored tool invoked,
    output lands at working/00_phase0/."""
    proj = _make_project(tmp_path)  # no papers/
    talk = _make_talk_draft(tmp_path)

    def _fake_extract_methods(argv):
        out_dir = Path(argv[argv.index("--output-dir") + 1])
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "methods_provenance.md").write_text(
            "originated methods\n", encoding="utf-8"
        )
        return 0

    with patch.object(
        pr.extract_methods, "main", side_effect=_fake_extract_methods
    ) as m:
        record, rc = pr.decide_and_act("methods_provenance", proj, talk)

    assert rc == 0
    assert record["decision"] == "originate"
    assert record["rationale"] == "paper_artifact_absent"
    assert record["source_path"] is None
    assert m.call_count == 1
    tp = DraftPaths.from_draft_dir(talk)
    assert tp.methods_provenance_phase0.read_text() == "originated methods\n"


def test_decide_originate_when_force_originate_set(tmp_path):
    """--force-originate bypasses reuse even when a paper artifact exists."""
    proj = _make_project(tmp_path)
    _make_paper_draft(proj, 1, "methods_provenance.md", "paper-writer methods\n")
    talk = _make_talk_draft(tmp_path)

    def _fake_extract_methods(argv):
        out_dir = Path(argv[argv.index("--output-dir") + 1])
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "methods_provenance.md").write_text(
            "originated despite paper\n", encoding="utf-8"
        )
        return 0

    with patch.object(
        pr.extract_methods, "main", side_effect=_fake_extract_methods
    ) as m:
        record, rc = pr.decide_and_act(
            "methods_provenance", proj, talk, force_originate=True
        )

    assert rc == 0
    assert record["decision"] == "originate"
    assert record["rationale"] == "force_originate"
    assert m.call_count == 1
    tp = DraftPaths.from_draft_dir(talk)
    assert tp.methods_provenance_phase0.read_text() == "originated despite paper\n"


# ---------------------------------------------------------------------------
# 10-11 — decide_and_act: no-op fast-path / hash-mismatch re-run
# ---------------------------------------------------------------------------

def test_decide_no_op_on_hash_match(tmp_path):
    """Existing artifact + prior stamp with matching hash → no-op, no copy,
    no tool invocation."""
    proj = _make_project(tmp_path)
    talk = _make_talk_draft(tmp_path)
    tp = DraftPaths.from_draft_dir(talk)
    tp.init_layout()
    tp.methods_provenance_phase0.write_text("existing methods\n", encoding="utf-8")
    # decide_and_act resolves project_dir internally — match it here so the
    # pre-computed hash aligns regardless of tmp_path's symlink form.
    current_hash = pr.compute_input_hash("methods_provenance", proj.resolve(), tp)
    _write_stamp(tp.audit, "methods_provenance", current_hash)

    with patch.object(pr.extract_methods, "main") as m:
        record, rc = pr.decide_and_act("methods_provenance", proj, talk)

    assert rc == 0
    assert record["decision"] == "no-op"
    assert record["rationale"] == "hashes_match"
    assert record["inputs_hashed"] == current_hash
    assert m.call_count == 0  # neither reuse-copy nor tool invocation
    assert tp.methods_provenance_phase0.read_text() == "existing methods\n"


def test_decide_re_run_on_hash_mismatch(tmp_path):
    """Existing artifact + prior stamp with a DIFFERENT hash → does not
    no-op; re-runs the decision (reuse here, paper draft present)."""
    proj = _make_project(tmp_path)
    _make_paper_draft(proj, 1, "methods_provenance.md", "fresh paper methods\n")
    talk = _make_talk_draft(tmp_path)
    tp = DraftPaths.from_draft_dir(talk)
    tp.init_layout()
    tp.methods_provenance_phase0.write_text("stale methods\n", encoding="utf-8")
    _write_stamp(tp.audit, "methods_provenance", "0" * 64)  # deliberately wrong

    record, rc = pr.decide_and_act("methods_provenance", proj, talk)

    assert rc == 0
    assert record["decision"] == "reuse"  # NOT no-op
    assert tp.methods_provenance_phase0.read_text() == "fresh paper methods\n"


def test_decide_no_op_skipped_when_prior_stamp_is_error(tmp_path):
    """A prior `error` stamp carrying a *matching* inputs_hashed must NOT
    trigger the no-op fast-path. A failed originate can leave a non-empty
    partial artifact on disk plus an error stamp that carries the hash;
    honoring it would silently retain bad output. Regression for Blocker #1
    of the M1 Tier C code review."""
    proj = _make_project(tmp_path)
    _make_paper_draft(proj, 1, "methods_provenance.md", "fresh paper methods\n")
    talk = _make_talk_draft(tmp_path)
    tp = DraftPaths.from_draft_dir(talk)
    tp.init_layout()
    # leftover non-empty artifact, as a failed originate would have left
    tp.methods_provenance_phase0.write_text("partial bad output\n", encoding="utf-8")
    # an `error` stamp carrying the CURRENT input hash — the poison case
    current_hash = pr.compute_input_hash("methods_provenance", proj.resolve(), tp)
    _write_stamp(tp.audit, "methods_provenance", current_hash, decision="error")

    record, rc = pr.decide_and_act("methods_provenance", proj, talk)

    assert rc == 0
    assert record["decision"] != "no-op"   # the error stamp is NOT honored
    assert record["decision"] == "reuse"   # decision re-runs (paper draft present)
    assert tp.methods_provenance_phase0.read_text() == "fresh paper methods\n"


# ---------------------------------------------------------------------------
# 12-13 — audit JSONL append + coexistence
# ---------------------------------------------------------------------------

def test_audit_jsonl_appended_not_overwritten(tmp_path):
    """Two decide+append cycles → two JSONL records, both valid JSON."""
    proj = _make_project(tmp_path)
    _make_paper_draft(proj, 1, "methods_provenance.md", "paper methods\n")
    talk = _make_talk_draft(tmp_path)
    tp = DraftPaths.from_draft_dir(talk)

    record1, _ = pr.decide_and_act("methods_provenance", proj, talk)
    pr.append_audit_record(tp.audit, record1)
    record2, _ = pr.decide_and_act("methods_provenance", proj, talk)
    pr.append_audit_record(tp.audit, record2)

    lines = (tp.audit / "phase0.jsonl").read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 2
    parsed = [json.loads(ln) for ln in lines]
    assert parsed[0]["decision"] == "reuse"
    assert parsed[1]["decision"] == "no-op"  # 2nd run hash-matches the 1st


def test_audit_jsonl_coexists_with_extract_claims_records(tmp_path):
    """A pre-existing extract_claims record in the shared phase0.jsonl is not
    clobbered; read_last_phase0_reuse_stamp skips it."""
    proj = _make_project(tmp_path)
    _make_paper_draft(proj, 1, "methods_provenance.md", "paper methods\n")
    talk = _make_talk_draft(tmp_path)
    tp = DraftPaths.from_draft_dir(talk)
    tp.init_layout()
    ec_record = {"tool": "extract_claims", "phase": "llm_extract", "exit_status": 0}
    with (tp.audit / "phase0.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(ec_record) + "\n")

    record, _ = pr.decide_and_act("methods_provenance", proj, talk)
    pr.append_audit_record(tp.audit, record)

    lines = (tp.audit / "phase0.jsonl").read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 2
    assert json.loads(lines[0])["tool"] == "extract_claims"
    assert json.loads(lines[1])["tool"] == "phase0_reuse"

    stamp = pr.read_last_phase0_reuse_stamp(tp.audit, "methods_provenance")
    assert stamp is not None
    assert stamp["tool"] == "phase0_reuse"


# ---------------------------------------------------------------------------
# 14 — --artifact all ordering
# ---------------------------------------------------------------------------

def test_artifact_all_runs_methods_then_claims(tmp_path):
    """--artifact all runs methods_provenance first (its output is present
    when claim_inventory's step runs)."""
    proj = _make_project(tmp_path)  # no papers/ → both originate
    talk = _make_talk_draft(tmp_path)
    tp = DraftPaths.from_draft_dir(talk)
    call_order: list[str] = []

    def _fake_methods(argv):
        call_order.append("methods")
        out_dir = Path(argv[argv.index("--output-dir") + 1])
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "methods_provenance.md").write_text("m\n", encoding="utf-8")
        return 0

    def _fake_claims(argv):
        call_order.append("claims")
        assert tp.methods_provenance_phase0.is_file(), "claims ran before methods"
        out = Path(argv[argv.index("--output") + 1])
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("claim_id\tclaim_text\nC1\tx\n", encoding="utf-8")
        return 0

    with patch.object(pr.extract_methods, "main", side_effect=_fake_methods), \
         patch.object(pr.extract_claims, "main", side_effect=_fake_claims):
        rc = pr.main([
            "--project-dir", str(proj),
            "--talk-draft-dir", str(talk),
            "--artifact", "all",
        ])

    assert rc == 0
    assert call_order == ["methods", "claims"]
    assert tp.methods_provenance_phase0.is_file()
    assert tp.claim_inventory_phase0.is_file()
    lines = (tp.audit / "phase0.jsonl").read_text(encoding="utf-8").strip().split("\n")
    p0_records = [
        json.loads(ln) for ln in lines
        if json.loads(ln)["tool"] == "phase0_reuse"
    ]
    assert len(p0_records) == 2
    assert {r["artifact"] for r in p0_records} == {
        "methods_provenance", "claim_inventory"
    }
    # cost_usd contract: methods_provenance originate is deterministic (0.0);
    # claim_inventory originate is null — extract_claims.py surfaces no real
    # LLM cost (Tier B simplification; see module docstring + Tier F5).
    by_artifact = {r["artifact"]: r for r in p0_records}
    assert by_artifact["methods_provenance"]["cost_usd"] == 0.0
    assert by_artifact["claim_inventory"]["cost_usd"] is None


# ---------------------------------------------------------------------------
# 15-17 — error / exit-code contract
# ---------------------------------------------------------------------------

def test_decide_claim_inventory_missing_methods_provenance_exits_1(tmp_path):
    """claim_inventory originate with no methods_provenance.md present →
    user error, exit 1."""
    proj = _make_project(tmp_path)
    talk = _make_talk_draft(tmp_path)

    record, rc = pr.decide_and_act("claim_inventory", proj, talk)

    assert rc == 1
    assert record["decision"] == "error"
    assert record["rationale"] == "missing_methods_provenance"
    assert "error_detail" in record


def test_decide_originate_subtool_failure_exits_2(tmp_path):
    """A vendored sub-tool returning non-zero on the originate path →
    exit 2, error record carries the sub-tool's exit code."""
    proj = _make_project(tmp_path)  # no papers/
    talk = _make_talk_draft(tmp_path)

    def _failing_extract_methods(argv):
        return 1  # sub-tool failed; no output written

    with patch.object(
        pr.extract_methods, "main", side_effect=_failing_extract_methods
    ):
        record, rc = pr.decide_and_act("methods_provenance", proj, talk)

    assert rc == 2
    assert record["decision"] == "error"
    assert record["rationale"] == "paper_artifact_absent"
    assert "extract_methods.main returned 1" in record["error_detail"]


def test_main_bad_project_dir_exits_1(tmp_path):
    """main() with a --project-dir that is not a directory → exit 1."""
    talk = _make_talk_draft(tmp_path)
    rc = pr.main([
        "--project-dir", str(tmp_path / "does_not_exist"),
        "--talk-draft-dir", str(talk),
        "--artifact", "methods_provenance",
    ])
    assert rc == 1
