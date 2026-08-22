from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .command import command_tools

if TYPE_CHECKING:
    from collections.abc import Iterable

    from .models import JsonValue, Plugin, Program


def plugin_fingerprint(conda_version: str, plugins: Iterable[Plugin]) -> str:
    """Fingerprint conda and its installed plugin entry-point metadata."""
    records = [
        {
            "distribution": plugin.distribution,
            "version": plugin.version,
            "entry_point": plugin.entry_point,
            "value": plugin.value,
            "hooks": sorted(plugin.hooks),
        }
        for plugin in plugins
    ]
    records.sort(
        key=lambda record: json.dumps(
            record,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    )
    payload = json.dumps(
        {"conda_version": conda_version, "plugins": records},
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class Capabilities:
    """Safe, immutable metadata for one discovered conda installation."""

    target_executable: str
    program: Program
    plugins: tuple[Plugin, ...]

    @property
    def generated_tools(self) -> tuple[str, ...]:
        """Return the generated tool names derived from the command catalog."""
        return tuple(tool.name for tool in command_tools(self.program))

    @property
    def discovery_fingerprint(self) -> str:
        """Return the restart-sensitive conda and plugin fingerprint."""
        return plugin_fingerprint(self.program.conda_version, self.plugins)

    def as_dict(self) -> dict[str, JsonValue]:
        """Return the stable, safe capability representation."""
        return {
            "target_executable": self.target_executable,
            "conda_version": self.program.conda_version,
            "catalog": self.program.as_dict(),
            "generated_tools": list(self.generated_tools),
            "plugins": [plugin.as_dict() for plugin in self.plugins],
            "discovery_fingerprint": self.discovery_fingerprint,
        }

    def to_json(self) -> str:
        """Serialize capabilities as deterministic JSON."""
        return json.dumps(
            self.as_dict(),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
