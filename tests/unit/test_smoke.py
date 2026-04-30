"""Smoke tests — confirm the package imports and CLI parser is sane.

Originally a v0.1.0-spec stub that asserted speculative subcommands
(`revise` etc) and stub-exit-2 behavior. Realigned in v0.3.0 to match
the actual CLI: 5 subcommands, all with real implementations.
"""
from __future__ import annotations

import pytest

import beril_presentation_maker
from beril_presentation_maker import cli


def test_version_attribute_exists():
    assert beril_presentation_maker.__version__.startswith("0.")


def test_cli_parser_builds_and_handles_version():
    parser = cli.build_parser()
    # argparse exits 0 on --version
    with pytest.raises(SystemExit) as exc_info:
        parser.parse_args(["--version"])
    assert exc_info.value.code == 0


def test_cli_subcommands_registered():
    """The five v0.3.0 subcommands are wired."""
    parser = cli.build_parser()
    sub_action = next(a for a in parser._actions if a.__class__.__name__ == "_SubParsersAction")
    assert set(sub_action.choices.keys()) == {
        "install-skill", "configure", "draft", "continue", "assemble"
    }


@pytest.mark.parametrize("subcmd", ["install-skill", "configure", "draft", "continue", "assemble"])
def test_each_subcommand_has_help(subcmd):
    """Every subcommand parser exposes --help without crashing."""
    parser = cli.build_parser()
    with pytest.raises(SystemExit) as exc_info:
        parser.parse_args([subcmd, "--help"])
    assert exc_info.value.code == 0
