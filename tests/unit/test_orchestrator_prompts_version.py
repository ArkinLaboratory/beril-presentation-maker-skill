"""Tests for the v0.5 Tier A `--prompts-version` flag wiring.

Per D-074: orchestrator accepts `--prompts-version {v1,v2,v3}`;
default v2; dispatcher helpers route substory_design + slide_compose
stages to the version-matched prompt file. Independent axis from
`--architecture-pipeline`.

Tests exercise the shell snippet directly via `bash -c` extraction
(mirrors test_orchestrator_image_provider.py pattern). The
dispatcher helpers are bash functions; we extract them + the
PROMPTS_DIR variable + invoke them with $PROMPTS_VERSION set.
"""
from __future__ import annotations

import re
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
ORCH_SH = (REPO_ROOT / "src" / "beril_presentation_maker" / "skill"
           / "tools" / "presentation_maker.sh")


def _run_dispatch(prompts_version: str, prompts_dir: Path,
                  helper: str,
                  slide_compose_v3_concat_path: str = "",
                  substory_design_v3_concat_path: str = "",
                  ) -> tuple[int, str, str]:
    """Invoke a dispatcher helper (`_substory_design_prompt_path` or
    `_slide_compose_prompt_path`) with the given PROMPTS_VERSION + a
    synthetic PROMPTS_DIR. Returns (rc, stdout, stderr).

    The helpers are defined in the orchestrator immediately after the
    --prompts-version validation block; we extract them by their
    function-name markers.

    Per v0.5.1/D-075 the v3 dispatcher returns the value of a shell
    variable populated by `build_v3_concat_prompts` at orchestrator
    start. For unit tests we pass the desired concat path in via the
    same shell-var names so the dispatcher echoes them back.
    """
    text = ORCH_SH.read_text(encoding="utf-8")
    # Pull the two helper definitions.
    helpers_block_start = text.find("_substory_design_prompt_path() {")
    helpers_block_end = text.find("\n}\n", text.find(
        "_slide_compose_prompt_path() {")) + 2
    if helpers_block_start < 0 or helpers_block_end < 2:
        raise AssertionError(
            "could not extract dispatcher helpers from orchestrator")
    helpers_src = text[helpers_block_start:helpers_block_end]

    wrapper = textwrap.dedent(f"""\
        set -euo pipefail
        PROMPTS_DIR={prompts_dir!s}
        PROMPTS_VERSION={prompts_version!r}
        SLIDE_COMPOSE_V3_CONCAT_PATH={slide_compose_v3_concat_path!r}
        SUBSTORY_DESIGN_V3_CONCAT_PATH={substory_design_v3_concat_path!r}
        {helpers_src}
        {helper}
        """)
    result = subprocess.run(
        ["bash", "-c", wrapper],
        capture_output=True, text=True, timeout=10,
    )
    return result.returncode, result.stdout.strip(), result.stderr


# ---------------------------------------------------------------------------
# Dispatcher helpers
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("version,expected_filename", [
    ("v1", "substory_design.v1.md"),
    ("v2", "substory_design.v1.md"),  # v2 reuses v1 substory_design
    # v3 substory_design currently still points at the standalone v3
    # file until D-078 / Tier A.2 lands the overlay split; the
    # dispatcher returns whatever SUBSTORY_DESIGN_V3_CONCAT_PATH was
    # set to at build time.
    ("v3", "substory_design.v3.md"),
])
def test_substory_design_dispatcher(version, expected_filename, tmp_path):
    """Per D-074: v1/v2 → v1 substory_design (identical contract);
    v3 → v3 substory_design (D-071 Q/A/R/C contract). Per D-075/D-078
    the v3 path comes from a build-time shell var; the test simulates
    that by setting the var to the expected path."""
    # For v3, simulate what build_v3_concat_prompts would populate.
    v3_path = f"{tmp_path}/{expected_filename}" if version == "v3" else ""
    rc, stdout, stderr = _run_dispatch(
        version, tmp_path, "_substory_design_prompt_path",
        substory_design_v3_concat_path=v3_path)
    assert rc == 0, f"helper failed: {stderr}"
    assert stdout == f"{tmp_path}/{expected_filename}"


@pytest.mark.parametrize("version,expected_filename", [
    ("v1", "slide_compose.v1.md"),
    ("v2", "slide_compose.v2.md"),
    # Per D-075 v3 is no longer a single file on disk — the dispatcher
    # returns the concat path populated at build time. The expected
    # "filename" here is the conventional name `build_v3_concat_prompts`
    # writes (`slide_compose.v3.concat.md` under audit/_prompts/).
    ("v3", "slide_compose.v3.concat.md"),
])
def test_slide_compose_dispatcher(version, expected_filename, tmp_path):
    """Per D-074: each version maps to a distinct slide_compose prompt.
    v0.5.1/D-075 changes the v3 contract: the dispatcher echoes the
    SLIDE_COMPOSE_V3_CONCAT_PATH shell var (populated at orchestrator
    start by build_v3_concat_prompts). The test simulates this by
    passing the synthetic concat path through the same shell var."""
    v3_path = f"{tmp_path}/{expected_filename}" if version == "v3" else ""
    rc, stdout, stderr = _run_dispatch(
        version, tmp_path, "_slide_compose_prompt_path",
        slide_compose_v3_concat_path=v3_path)
    assert rc == 0, f"helper failed: {stderr}"
    assert stdout == f"{tmp_path}/{expected_filename}"


# ---------------------------------------------------------------------------
# Flag validation
# ---------------------------------------------------------------------------

def test_invalid_prompts_version_exits_2(tmp_path):
    """Per D-074: --prompts-version must be v1|v2|v3; anything else
    exits 2 with a clear error. The validation runs after BERIL_ROOT/
    project resolution so we need a project that exists; using an
    existing v0.5-vintage project keeps the test fast."""
    # Use an existing fixture project; we expect to exit at the
    # --prompts-version validation step, BEFORE any pipeline work.
    beril_root = (Path("/Users/aparkin/Documents/Claude/Projects/"
                       "research-coscientist-dev/spike/beril-extended"))
    project = "ibd_phage_targeting"
    result = subprocess.run(
        ["bash", str(ORCH_SH), project,
         "--beril-root", str(beril_root),
         "--prompts-version", "v9"],
        capture_output=True, text=True, timeout=20,
    )
    assert result.returncode == 2, (
        f"expected rc=2 on invalid version; got {result.returncode}")
    assert "--prompts-version must be" in result.stderr
    assert "v9" in result.stderr


def test_help_includes_prompts_version_flag():
    """Discoverability: --help output names --prompts-version flag +
    the three valid values."""
    result = subprocess.run(
        ["bash", str(ORCH_SH), "--help"],
        capture_output=True, text=True, timeout=10,
    )
    help_text = result.stdout + result.stderr
    assert "--prompts-version" in help_text
    # All three valid values mentioned somewhere in the flag docs
    assert "v1" in help_text
    assert "v2" in help_text
    assert "v3" in help_text
    # D-074 default-v2 posture mentioned
    assert "v2" in help_text and "Default" in help_text


# ---------------------------------------------------------------------------
# v3 prompt-file existence (pre-flight)
# ---------------------------------------------------------------------------

def test_v3_prompt_files_present_in_pre_flight_check():
    """v0.5.1/D-075 update: v3 slide_compose is now the OVERLAY file
    (`slide_compose.v3_overlay.md`), not the broken standalone v3.md.
    The pre-flight check must require both substory_design.v3.md
    (still standalone until D-078 / Tier A.2 lands) and
    slide_compose.v3_overlay.md (the new v3 overlay)."""
    text = ORCH_SH.read_text(encoding="utf-8")
    # Find the pre-flight for loop
    pattern = r'^for f in (.+?); do$'
    matches = re.findall(pattern, text, re.MULTILINE)
    # Find the one containing slide_compose
    loop_line = next((m for m in matches if "slide_compose" in m), "")
    assert "substory_design.v3.md" in loop_line, (
        f"pre-flight prompt loop missing substory_design.v3.md; "
        f"got: {loop_line}")
    assert "slide_compose.v3_overlay.md" in loop_line, (
        f"pre-flight prompt loop missing slide_compose.v3_overlay.md; "
        f"got: {loop_line}")
    # The old standalone v3.md must NOT be referenced — it was deleted
    # at v0.5.1 Tier A (D-075 root-cause fix).
    assert "slide_compose.v3.md" not in loop_line, (
        f"pre-flight still references retired slide_compose.v3.md; "
        f"replace with slide_compose.v3_overlay.md per D-075. "
        f"got: {loop_line}")


# ---------------------------------------------------------------------------
# v0.5 Tier A.2 — SUBSTORY_QUESTION/CONCLUSION user-prompt wiring (D-071/D-072)
# ---------------------------------------------------------------------------
#
# The v3 slide_compose.v3.md prompt documents 3 user-prompt inputs that
# v2 doesn't have: SUBSTORY_QUESTION, SUBSTORY_CONCLUSION, ALLOWLIST_TERMS.
# Tier A.2 wired these through both slide-compose paths (v0_4 parallel +
# v0_3 sequential). Gate: only injected when --prompts-version v3.

def test_v0_4_user_prompt_injects_v3_fields_when_prompts_version_v3():
    """The v0_4 _compose_one_substory builder must include the three
    v3 user-prompt fields (SUBSTORY_QUESTION, SUBSTORY_CONCLUSION,
    ALLOWLIST_TERMS) inside a PROMPTS_VERSION=v3 gate."""
    text = ORCH_SH.read_text(encoding="utf-8")
    # Locate the v0_4 path's v3-gated injection block.
    # Look for the conditional block that adds SUBSTORY_QUESTION etc.
    assert 'SUBSTORY_QUESTION=$sub_question' in text, (
        "v3-gated injection of SUBSTORY_QUESTION missing")
    assert 'SUBSTORY_CONCLUSION=$sub_conclusion' in text, (
        "v3-gated injection of SUBSTORY_CONCLUSION missing")
    # ALLOWLIST_TERMS appears in BOTH v0_4 + v0_3 paths
    assert 'ALLOWLIST_TERMS=' in text, (
        "v3-gated injection of ALLOWLIST_TERMS missing")
    # Gate must be PROMPTS_VERSION=v3 (else injection happens on v1/v2 too)
    assert 'PROMPTS_VERSION" == "v3"' in text or \
           'PROMPTS_VERSION = v3' in text, (
        "v3 injection block missing PROMPTS_VERSION=v3 gate")


def test_v0_4_prepopulates_question_conclusion_brief_when_v3():
    """The v0_4 setup block (before per-substory compose) must
    pre-populate _M3_BRIEF_QUESTIONS + _M3_BRIEF_CONCLUSIONS via
    parse_deck_outline.py — and only when PROMPTS_VERSION=v3 (we
    don't pay parse-cost on v1/v2 paths)."""
    text = ORCH_SH.read_text(encoding="utf-8")
    assert '_M3_BRIEF_QUESTIONS=' in text
    assert '_M3_BRIEF_CONCLUSIONS=' in text
    # And they're set inside a v3 gate (not unconditional)
    # Find the line numbers of the assignments
    lines = text.splitlines()
    questions_line = next(
        (i for i, line in enumerate(lines) if '_M3_BRIEF_QUESTIONS=' in line
         and '_m3_outline_field' in line), None)
    assert questions_line is not None, (
        "could not find _M3_BRIEF_QUESTIONS assignment with _m3_outline_field")
    # Look back ~10 lines for a PROMPTS_VERSION check
    preceding = "\n".join(lines[max(0, questions_line - 10):questions_line])
    assert 'PROMPTS_VERSION" == "v3"' in preceding, (
        "_M3_BRIEF_QUESTIONS assignment not gated by PROMPTS_VERSION=v3")


def test_v0_3_path_also_wires_v3_fields_when_prompts_version_v3():
    """The v0_3 sequential path (_slide_compose_v0_3) must ALSO
    wire SUBSTORY_QUESTION + SUBSTORY_CONCLUSION + ALLOWLIST_TERMS
    when PROMPTS_VERSION=v3, since v0_3 + v3 is a valid combination
    per D-074."""
    text = ORCH_SH.read_text(encoding="utf-8")
    # Locate the v0_3 function
    v0_3_start = text.find("_slide_compose_v0_3() {")
    assert v0_3_start > 0
    # Walk forward to find the function's end (next `^}` at column 0)
    # — heuristic: function bodies in this script are short enough that
    # the next `\n}\n` is the closer.
    v0_3_end = text.find("\n}\n", v0_3_start) + 2
    v0_3_body = text[v0_3_start:v0_3_end]
    # The body must contain v3-gated injection
    assert 'SUBSTORY_QUESTION=$sub_question' in v0_3_body, (
        "v0_3 path missing SUBSTORY_QUESTION v3-gated injection")
    assert 'SUBSTORY_CONCLUSION=$sub_conclusion' in v0_3_body, (
        "v0_3 path missing SUBSTORY_CONCLUSION v3-gated injection")
    assert 'PROMPTS_VERSION" == "v3"' in v0_3_body, (
        "v0_3 path missing PROMPTS_VERSION=v3 gate")


def test_parse_deck_outline_supports_v3_question_conclusion_fields():
    """parse_deck_outline.py --field {questions,conclusions} must be
    valid (the orchestrator's _m3_outline_field helper calls them).
    Quick sanity check via --help."""
    result = subprocess.run(
        [sys.executable,
         str(REPO_ROOT / "src/beril_presentation_maker/skill/tools/parse_deck_outline.py"),
         "--help"],
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0
    help_text = result.stdout + result.stderr
    assert "questions" in help_text
    assert "conclusions" in help_text


def test_allowlist_loaded_from_project_dir_when_v3():
    """Per D-072: when PROMPTS_VERSION=v3, the orchestrator loads
    references/register_allowlist.md from PROJECT_DIR and injects as
    ALLOWLIST_TERMS (comma-separated). The load uses grep to strip
    comments + blanks."""
    text = ORCH_SH.read_text(encoding="utf-8")
    # The allowlist path pattern must reference references/register_allowlist.md
    assert "references/register_allowlist.md" in text
    # Loaded via grep + tr to comma-separated string
    assert "register_allowlist.md" in text and "tr '\\n' ','" in text


# ---------------------------------------------------------------------------
# v0.5.1 Tier A — build_v3_concat_prompts() (D-075)
# ---------------------------------------------------------------------------
#
# build_v3_concat_prompts() runs once at orchestrator start (after
# set_draft_paths) and produces:
#   $AUDIT_DIR/_prompts/slide_compose.v3.concat.md
# = cat slide_compose.v2.md slide_compose.v3_overlay.md
#
# It populates SLIDE_COMPOSE_V3_CONCAT_PATH so the dispatcher echoes
# the concat path on --prompts-version v3.

def _extract_function(text: str, fname: str) -> str:
    """Pull a bash function body (including the `name() { ... }`)
    out of the orchestrator source. Heuristic — the orchestrator's
    function bodies are short and end at `^}` at column 0."""
    start = text.find(f"{fname}() {{")
    if start < 0:
        raise AssertionError(f"could not locate function {fname}")
    end = text.find("\n}\n", start) + 2
    return text[start:end]


def test_build_v3_concat_creates_audit_prompts_file(tmp_path):
    """build_v3_concat_prompts must write the concat file under
    $AUDIT_DIR/_prompts/ with v2 body first + v3 overlay last."""
    text = ORCH_SH.read_text(encoding="utf-8")
    fn_src = _extract_function(text, "build_v3_concat_prompts")
    # Stage fake v2 + v3 overlay sources to verify cat order.
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    (prompts_dir / "slide_compose.v2.md").write_text(
        "==V2-BODY-MARKER==\nv2 content\n", encoding="utf-8")
    (prompts_dir / "slide_compose.v3_overlay.md").write_text(
        "==V3-OVERLAY-MARKER==\noverlay content\n", encoding="utf-8")
    audit_dir = tmp_path / "audit"
    audit_dir.mkdir()
    # substory_design v3 (D-078 stub) — function reads this; provide
    # a placeholder so the substring-substitute doesn't trip ENOENT.
    (prompts_dir / "substory_design.v3.md").write_text(
        "stub\n", encoding="utf-8")

    wrapper = textwrap.dedent(f"""\
        set -euo pipefail
        PROMPTS_VERSION=v3
        PROMPTS_DIR={prompts_dir!s}
        AUDIT_DIR={audit_dir!s}
        SLIDE_COMPOSE_V3_CONCAT_PATH=""
        SUBSTORY_DESIGN_V3_CONCAT_PATH=""
        {fn_src}
        build_v3_concat_prompts
        echo "RET_SLIDE=$SLIDE_COMPOSE_V3_CONCAT_PATH"
        echo "RET_SUBSTORY=$SUBSTORY_DESIGN_V3_CONCAT_PATH"
        """)
    result = subprocess.run(["bash", "-c", wrapper],
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr

    concat_path = audit_dir / "_prompts" / "slide_compose.v3.concat.md"
    assert concat_path.is_file(), (
        f"build_v3_concat_prompts didn't write concat file at "
        f"{concat_path}; stderr: {result.stderr}")
    body = concat_path.read_text(encoding="utf-8")
    # v2 body must come FIRST (so the overlay at the tail wins on
    # LLM attention; per D-075 rationale).
    v2_pos = body.find("==V2-BODY-MARKER==")
    overlay_pos = body.find("==V3-OVERLAY-MARKER==")
    assert v2_pos >= 0, "concat missing v2 body marker"
    assert overlay_pos >= 0, "concat missing v3 overlay marker"
    assert v2_pos < overlay_pos, (
        f"concat order wrong: v2 at pos {v2_pos}, overlay at pos "
        f"{overlay_pos}; overlay must come LAST")

    # And the shell vars must be populated for the dispatcher.
    assert f"RET_SLIDE={concat_path}" in result.stdout


def test_build_v3_concat_no_op_for_v1_v2(tmp_path):
    """build_v3_concat_prompts must early-return when PROMPTS_VERSION
    is not v3 (no concat, no shell-var population)."""
    text = ORCH_SH.read_text(encoding="utf-8")
    fn_src = _extract_function(text, "build_v3_concat_prompts")
    audit_dir = tmp_path / "audit"
    audit_dir.mkdir()
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()

    for version in ("v1", "v2"):
        wrapper = textwrap.dedent(f"""\
            set -euo pipefail
            PROMPTS_VERSION={version}
            PROMPTS_DIR={prompts_dir!s}
            AUDIT_DIR={audit_dir!s}
            SLIDE_COMPOSE_V3_CONCAT_PATH=""
            SUBSTORY_DESIGN_V3_CONCAT_PATH=""
            {fn_src}
            build_v3_concat_prompts
            echo "RET_SLIDE=$SLIDE_COMPOSE_V3_CONCAT_PATH"
            """)
        result = subprocess.run(["bash", "-c", wrapper],
                                capture_output=True, text=True, timeout=10)
        assert result.returncode == 0, result.stderr
        # No concat file written.
        assert not (audit_dir / "_prompts" /
                    "slide_compose.v3.concat.md").exists()
        # Shell var stays empty.
        assert "RET_SLIDE=" in result.stdout
        # The line should be exactly "RET_SLIDE=" (nothing after =).
        for line in result.stdout.splitlines():
            if line.startswith("RET_SLIDE="):
                assert line == "RET_SLIDE=", (
                    f"v1/v2 path leaked into concat path: {line!r}")


def test_v3_overlay_file_present_on_disk():
    """Belt + suspenders: the v3 overlay file actually exists at the
    expected path in the repo (so build_v3_concat_prompts won't fail
    with ENOENT at orchestrator start)."""
    overlay = (REPO_ROOT / "src" / "beril_presentation_maker" / "skill"
               / "prompts" / "slide_compose.v3_overlay.md")
    assert overlay.is_file(), f"v3 overlay missing at {overlay}"
    # Body should reference v2 explicitly (overlay marker stating it
    # depends on v2 above).
    body = overlay.read_text(encoding="utf-8")
    assert "v3 overlay" in body.lower(), (
        "overlay file doesn't self-identify as v3 overlay")
    assert "v2" in body, (
        "overlay doesn't reference v2 — concat assumption suspect")


def test_old_standalone_v3_file_retired():
    """v0.5.1 Tier A retires `slide_compose.v3.md` (the broken
    standalone file). The file MUST be gone — its content lives in
    `slide_compose.v3_overlay.md` + `slide_compose.v2.md` via the
    concat. Belt-and-suspenders against a future accidental
    re-creation."""
    old_v3 = (REPO_ROOT / "src" / "beril_presentation_maker" / "skill"
              / "prompts" / "slide_compose.v3.md")
    assert not old_v3.exists(), (
        f"standalone v3 file came back at {old_v3}; v0.5.1/D-075 "
        f"replaced it with slide_compose.v3_overlay.md. If you "
        f"intentionally re-introduced it, update this test + the "
        f"dispatcher to match.")
