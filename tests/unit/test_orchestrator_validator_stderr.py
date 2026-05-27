"""Unit tests for v0.6 Tier B (D-083) — validator stderr redirect.

Per the v0.5.1 Tier D live failure, the orchestrator piped
slide_spec.py validate's stderr through `tee` and hit
BlockingIOError on a soft-warning-heavy spec. The pipe-buffer
back-pressure crashed Python mid-print, the non-zero rc fired
the orchestrator's "validation FAILED" path, and the deck never
rendered.

D-083 fix: redirect the validator's stderr to a file
(`$AUDIT_DIR/validate.stderr`), then cat that file to
orchestrator stderr in one all-at-once write. No pipe
back-pressure on a buffered file.

These tests pin the redirect pattern at both validate call sites
(stage_merge_and_assemble + the post-revise re-validation) so a
future refactor can't accidentally drop the protection.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ORCH_SH = (REPO_ROOT / "src" / "beril_presentation_maker" / "skill"
           / "tools" / "presentation_maker.sh")


def test_main_validate_call_redirects_stderr_to_file():
    """The validate call inside stage_merge_and_assemble must
    redirect stderr (`2>`) to a file (either an audit-dir-anchored
    path OR a local var that holds one). Pin the structural intent
    so future refactors can't regress to the unsafe-tee version."""
    text = ORCH_SH.read_text(encoding="utf-8")
    # Find the stage_merge_and_assemble function body.
    fn_start = text.find("stage_merge_and_assemble() {")
    assert fn_start > 0
    fn_end = text.find("\n}\n", fn_start)
    body = text[fn_start:fn_end]

    # Locate the validate invocation + accept the next ~3 lines as
    # the relevant span (the `2>` may live on the next line under
    # `\` continuation).
    validate_pos = body.find('slide_spec.py" validate "$spec"')
    assert validate_pos >= 0, "validate invocation not found"
    span = body[validate_pos:validate_pos + 400]
    # The redirect must point at a path or a stderr-file shell var.
    pattern = re.compile(
        r'2> +"(?:\$AUDIT_DIR/[^"]+\.stderr|\$_validate_stderr)"',
        re.MULTILINE)
    assert pattern.search(span), (
        "stage_merge_and_assemble must redirect validate stderr to "
        "a file under $AUDIT_DIR (D-083 fix). Got span:\n"
        + span[:400])


def test_post_revise_validate_call_redirects_stderr_to_file():
    """The post-revise re-validation site (in the revise_loop's
    re-assemble branch) must also redirect stderr per D-083 —
    same bug class applies if a revised spec has many soft-warnings."""
    text = ORCH_SH.read_text(encoding="utf-8")
    # Search for the "post-revise validation FAILED" marker; the
    # validate call sits a few lines before it.
    marker = text.find("post-revise validation FAILED")
    assert marker > 0, "post-revise validation site not found"
    # Walk back ~25 lines (~1.5KB) to find the validate invocation.
    block_start = max(0, marker - 1500)
    block = text[block_start:marker]
    # Same flexible pattern as the main-validate test (accepts
    # AUDIT_DIR-anchored path OR local stderr var).
    pattern = re.compile(
        r'2> +"(?:\$[A-Z_]+/[^"]+\.stderr|\$_[a-z_]+_stderr)"',
        re.MULTILINE)
    assert pattern.search(block), (
        "post-revise validation must redirect stderr to a file "
        "(D-083 fix); same bug class as Tier B main site. Got "
        f"block:\n{block[-800:]}")


def test_validate_failure_path_dumps_stderr_to_orchestrator_stderr():
    """On validation failure, the orchestrator must `cat` the
    stderr file to its own stderr so operators see the errors.
    Otherwise the stderr redirect would hide the failure cause."""
    text = ORCH_SH.read_text(encoding="utf-8")
    fn_start = text.find("stage_merge_and_assemble() {")
    fn_end = text.find("\n}\n", fn_start)
    body = text[fn_start:fn_end]
    # On failure: cat the stderr file + reference its path. The
    # `[[ -s ... ]] && cat` idiom is what the fix uses; we match
    # the structural intent.
    assert "validation FAILED" in body
    # After the validate call, on the failure branch, the file
    # must be cat'd. Pattern: cat "$_validate_stderr" or
    # cat "$AUDIT_DIR/...stderr" or similar.
    fail_branch_pos = body.find("validation FAILED")
    fail_branch = body[fail_branch_pos:fail_branch_pos + 800]
    assert re.search(r'cat +"\$_[a-z_]+_stderr"', fail_branch) or \
           re.search(r'cat +"\$[A-Z_]+/[^"]+\.stderr"', fail_branch), (
        "validation failure path must cat the stderr file to "
        "orchestrator stderr. Got branch:\n" + fail_branch[:500])


def test_validate_success_path_also_dumps_stderr_for_soft_warnings():
    """On validation SUCCESS with soft-warnings (the v0.5.1 fdm
    scenario — 0 errors + 11 soft-warnings), the orchestrator
    must STILL cat the stderr file so operators see the
    soft-warnings. Otherwise the redirect hides advisory output
    on every successful run."""
    text = ORCH_SH.read_text(encoding="utf-8")
    fn_start = text.find("stage_merge_and_assemble() {")
    fn_end = text.find("\n}\n", fn_start)
    body = text[fn_start:fn_end]
    # After the validate call, on the success branch (after the
    # closing `fi` or `}` of the failure if-block), the stderr
    # file must be cat'd unconditionally. This is what makes the
    # behavior equivalent to the pre-fix "stderr-piped-through-tee"
    # except without the pipe-buffer hazard.
    #
    # Pattern: a `cat "$_validate_stderr" >&2` (or equivalent)
    # appearing AFTER the failure branch's closing brace/fi.
    # Count occurrences of the cat-stderr-file idiom; should be
    # >= 2 (one in failure branch, one in success).
    cat_stderr_count = len(re.findall(
        r'cat +"\$_validate_stderr"', body))
    assert cat_stderr_count >= 2, (
        f"expected cat of validate-stderr file in BOTH failure "
        f"(error context) and success (soft-warnings) paths "
        f"(D-083 requires success-path output for parity); "
        f"got {cat_stderr_count} cat occurrences.")
