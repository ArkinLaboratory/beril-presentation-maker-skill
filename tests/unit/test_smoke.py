"""v0.1.0-spec smoke tests — confirm the package imports and CLI parses.

These are the only tests in v0.1.0-spec. The rest land with
implementation per LAYOUT.md §11 'Tests (planned)'.
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
    parser = cli.build_parser()
    # Pull subparser choices off the subparsers action
    sub_action = next(a for a in parser._actions if a.__class__.__name__ == "_SubParsersAction")
    assert set(sub_action.choices.keys()) == {"install-skill", "configure", "continue", "assemble", "revise"}


@pytest.mark.parametrize("subcmd,extra_args", [
    ("install-skill", []),
    ("configure", []),
    ("continue", ["/tmp/fake_draft"]),
    ("assemble", ["/tmp/fake_draft"]),
    ("revise", ["/tmp/fake_draft", "--slide", "3", "tighten the punchline"]),
])
def test_cli_subcommands_stub_exit_2(subcmd, extra_args):
    """Every subcommand exits with code 2 (stub-not-implemented) in spec release."""
    parser = cli.build_parser()
    parsed = parser.parse_args([subcmd, *extra_args])
    with pytest.raises(SystemExit) as exc_info:
        parsed.func(parsed)
    assert exc_info.value.code == 2


def test_revise_requires_a_scope():
    parser = cli.build_parser()
    # No scope flag → argparse errors out (mutually exclusive required group)
    with pytest.raises(SystemExit):
        parser.parse_args(["revise", "/tmp/fake", "instruction"])
