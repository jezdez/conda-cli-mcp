from __future__ import annotations

import json
from dataclasses import replace

import pytest

from conda_cli_mcp.capabilities import Capabilities, plugin_fingerprint
from conda_cli_mcp.models import Command, Plugin, Program


def make_program(version: str = "26.7.1") -> Program:
    return Program(
        prog="conda",
        conda_version=version,
        root=Command(
            name=None,
            terminal=False,
            children=(Command(name="info"), Command(name="opaque", raw_only=True)),
        ),
    )


def make_plugin(
    *,
    distribution: str = "conda-example",
    version: str = "1.2.3",
    entry_point: str = "example",
    value: str = "conda_example.plugin",
    hooks: tuple[str, ...] = ("conda_solvers", "conda_subcommands"),
) -> Plugin:
    return Plugin(
        distribution=distribution,
        version=version,
        entry_point=entry_point,
        value=value,
        hooks=hooks,
    )


def test_capabilities_derive_and_round_trip_safe_catalog_metadata() -> None:
    program = make_program()
    plugin = make_plugin()
    capabilities = Capabilities(
        target_executable="/opt/conda/bin/conda",
        program=program,
        plugins=(plugin,),
    )

    assert capabilities.generated_tools == ("conda_info",)
    assert capabilities.as_dict() == {
        "target_executable": "/opt/conda/bin/conda",
        "conda_version": "26.7.1",
        "catalog": program.as_dict(),
        "generated_tools": ["conda_info"],
        "plugins": [plugin.as_dict()],
        "discovery_fingerprint": capabilities.discovery_fingerprint,
    }
    assert json.loads(capabilities.to_json()) == capabilities.as_dict()


def test_plugin_fingerprint_ignores_plugin_and_hook_order() -> None:
    first = make_plugin()
    second = make_plugin(
        distribution="conda-other",
        entry_point="other",
        value="conda_other.plugin",
        hooks=("conda_reporter_backends",),
    )

    expected = plugin_fingerprint("26.7.1", (first, second))

    assert len(expected) == 64
    assert int(expected, 16) >= 0
    assert plugin_fingerprint("26.7.1", (second, first)) == expected
    assert (
        plugin_fingerprint(
            "26.7.1",
            (replace(first, hooks=tuple(reversed(first.hooks))), second),
        )
        == expected
    )


@pytest.mark.parametrize(
    "changed",
    [
        make_plugin(distribution="renamed"),
        make_plugin(version="2.0"),
        make_plugin(entry_point="renamed"),
        make_plugin(value="conda_example.other"),
        make_plugin(hooks=("conda_subcommands",)),
    ],
)
def test_plugin_fingerprint_changes_with_discovery_inputs(changed: Plugin) -> None:
    original = make_plugin()
    expected = plugin_fingerprint("26.7.1", (original,))

    assert plugin_fingerprint("26.7.1", (changed,)) != expected
    assert plugin_fingerprint("26.8.0", (original,)) != expected
