# MCP interface reference

The MCP interface consists of startup-generated structured tools, one optional
raw argv tool, one read-only resource, and a common execution result.

## Generated tools

Each representable terminal argparse command receives one canonical tool. Tool
names begin with `conda_` and join the canonical command path with underscores,
such as `conda_info` or `conda_env_create`. Aliases are metadata on the
canonical tool rather than separate tools.

Input schemas preserve supported argparse behavior, including:

- required and optional values
- strings, integers, numbers, booleans, counts, and arrays
- choices and repeated options
- positional order
- mutually exclusive groups
- nested commands
- opaque passthrough arrays for greedy plugin parsers

Unsupported parser actions mark an affected command as raw-only. Generated
string positionals reject option-like values. Use raw argv when a command
intentionally requires such a value.

Generated tool metadata includes the canonical conda path and aliases. MCP
annotations describe read-only, destructive, idempotent, and open-world
behavior. The server enforces policy independently of those annotations.

## Conda completion metadata tool

`conda_cli_command` is listed when the target plugin inventory contains
`conda-completion`. Version 0.3 or newer supplies the public API used to read
one command from that target installation's generated `completion.msgpack`.
The tool reports older versions as unavailable and never regenerates the file.

The optional `command_path` input is an array of canonical command tokens. An
empty array selects the root. For example:

```json
{
  "command_path": ["env", "list"]
}
```

The result includes command options, positionals, direct subcommands,
exclusive groups, completion types and rules, runtime-source definitions,
executable-alias resolution, manifest metadata, and plugin-hash staleness.
Package-name and package-version caches are not returned.

The staleness flag compares registered plugin entry-point names. It does not
detect a plugin update that keeps the same entry-point name or an unrelated
conda parser change.

`availability` is `available`, `not_installed`, `not_generated`, or
`unavailable`. A missing cache includes a hint to run
`conda completion generate` in the target environment. Unknown command paths
are rejected as invalid input. The tool is read-only and does not require a
safety-policy option.

## Raw argv tool

`conda_execute` is listed only when the server starts with `--allow-exec`.

| Input | Type | Required | Meaning |
| --- | --- | --- | --- |
| `argv` | array of strings | yes | Arguments passed directly after the conda executable |
| `cwd` | string | no | Working directory for the child process |
| `stdin` | string | no | Bounded noninteractive standard input |
| `timeout_seconds` | positive number | no | Shorter timeout for this call, capped by the server limit |

The input object rejects unknown fields. The server invokes the executable with
an argv list and never invokes a shell.

## Capabilities resource

`conda://capabilities` is an immutable JSON resource with these top-level
fields:

| Field | Meaning |
| --- | --- |
| `target_executable` | Resolved conda executable path |
| `conda_version` | Version reported by the target |
| `catalog` | Complete immutable argparse-derived command catalog and diagnostics |
| `generated_tools` | Canonical structured tool names |
| `plugins` | External conda entry-point distributions, versions, values, and detected hooks |
| `discovery_fingerprint` | Digest used to detect restart-sensitive changes |

The resource does not include credentials, authentication objects, request
headers, or complete process environments.

## Execution result

Raw and generated tools return the same structured result:

| Field | Type | Meaning |
| --- | --- | --- |
| `exit_code` | integer or null | Child exit status, or null after a timeout |
| `stdout` | string | Retained standard output |
| `stderr` | string | Retained standard error |
| `duration_ms` | integer | Elapsed execution time in milliseconds |
| `parsed_json` | any JSON value or null | Stdout parsed only when it is one complete JSON document |
| `timed_out` | boolean | Whether the configured timeout ended the process |
| `cancelled` | boolean | Internal cancellation result state, normally false for completed calls |
| `stdout_truncated` | boolean | Whether standard output exceeded its retained-byte limit |
| `stderr_truncated` | boolean | Whether standard error exceeded its retained-byte limit |
| `restart_required` | boolean | Whether the fixed startup catalog should be refreshed |

Text content contains a concise summary and a serialized copy of the structured
result for clients without structured-content support. A nonzero exit code or
timeout marks the MCP tool result as an error. Original output is preserved
even when `parsed_json` is populated. Truncated output is not parsed as JSON.

## Errors and cancellation

Schema errors identify the invalid JSON path without echoing submitted values.
Policy errors name the required startup option. Unknown tools and resources do
not disclose internal catalog details.

On client cancellation, the server terminates the process tree and propagates
request cancellation, so no tool result is returned. On timeout, it terminates
the process tree, waits for a bounded grace period, and kills remaining
processes if necessary. Conda executions are serialized within one server
process.
