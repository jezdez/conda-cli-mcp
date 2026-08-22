# Architecture and plugin participation

`conda-cli-mcp` adapts the command line accepted by a selected conda
installation. It does not replace conda's command dispatcher or expose each
plugin hook as a separate protocol concept.

## Startup discovery

The server first asks the selected executable for `conda info --json`. This
identifies the target conda version and the Python interpreter associated with
that installation.

A short-lived helper under that interpreter asks conda to construct its
argparse parser. The discovery adapter traverses the configured parser and
immediately converts it into immutable command and argument values. Runtime
server code does not retain argparse objects or conda's global context. The
helper imports conda from the selected target environment rather than from the
server environment.

Argparse does not provide a public command-tree inspection API, so the adapter
contains the compatibility-sensitive traversal in one module. Unsupported
actions produce diagnostics and preserve raw reachability rather than silently
dropping a command.

The resulting catalog is fixed for the server lifetime. This gives MCP clients
a stable tool list and avoids loading conda's long-lived mutable state into the
server process.

## Structured tools and raw reachability

Representable terminal commands become structured tools with JSON Schemas.
Their inputs compile back to canonical argv before execution. Canonical paths
produce deterministic names, while aliases remain metadata.

The optional raw tool accepts argv directly. It covers unsupported parser
features, intentional option-like positionals, and commands whose interface is
opaque. Requiring `--allow-exec` keeps that escape hatch out of the default
server surface.

Both forms enter the same safety classifier and child-process executor. Conda
therefore receives the final argv and remains responsible for its own parser
validation and behavior.

## Plugin behavior

Conda builds its parser with installed `conda_subcommands` contributions, so
plugin commands join the same discovery tree as built-in commands. A configured
plugin parser can receive a structured tool. A greedy parser can expose an
explicit passthrough array, subject to process execution policy.

Other hooks already participate when conda executes. This includes command,
solver, transaction, reporter, authentication, and related hooks. Mirroring
those hooks as MCP tools would bypass conda's ordering and lifecycle, so the
server leaves them under conda's control.

External entry-point metadata is recorded in the capabilities resource. A
fingerprint over conda and that metadata detects changes after operations that
could alter the installed plugin set. The server reports a required restart
without changing tools in place.

When the target includes `conda-completion`, the server adds one read-only
metadata tool. Its short-lived target helper calls conda-completion's public
`manifest_path`, `read_manifest`, and plugin-hash interfaces. The MCP package
does not reconstruct platform cache paths, decode MessagePack itself, or keep
a second command catalog. Conda's startup argparse catalog remains
authoritative for generated tools. The completion data only supplies hints
that are unique to conda-completion.

## Process isolation

Every invocation runs the selected conda executable in a fresh child process.
The server passes an argv list directly, bounds time and retained I/O, and
serializes executions. Cancellation terminates and reaps the process tree.

This separation lets each invocation load current conda configuration and run
normal plugin hooks while keeping the MCP service independent of target conda
module state.
