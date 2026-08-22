from __future__ import annotations

from dataclasses import dataclass

JsonScalar = str | int | float | bool | None
JsonValue = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    """Structured outcome of one conda child process."""

    exit_code: int | None
    stdout: str
    stderr: str
    duration_ms: int
    parsed_json: JsonValue | None = None
    timed_out: bool = False
    cancelled: bool = False
    stdout_truncated: bool = False
    stderr_truncated: bool = False
    restart_required: bool = False

    @property
    def failed(self) -> bool:
        return self.exit_code not in (0, None) or self.timed_out or self.cancelled

    def as_dict(self) -> dict[str, JsonValue]:
        """Return the stable MCP structured-output representation."""
        return {
            "exit_code": self.exit_code,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "duration_ms": self.duration_ms,
            "parsed_json": self.parsed_json,
            "timed_out": self.timed_out,
            "cancelled": self.cancelled,
            "stdout_truncated": self.stdout_truncated,
            "stderr_truncated": self.stderr_truncated,
            "restart_required": self.restart_required,
        }

    def summary(self) -> str:
        """Return a concise text result for MCP clients without structured output."""
        if self.timed_out:
            return "conda command timed out"
        if self.cancelled:
            return "conda command was cancelled"
        return f"conda command exited with {self.exit_code}"
