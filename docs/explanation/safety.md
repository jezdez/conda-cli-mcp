# Safety model

The safety model separates discovery from authority. Generated mutation tools
remain discoverable so the MCP interface stays stable, while startup policy
determines whether a call may spawn conda.

## Read-only by default

Without policy options, the server permits commands classified as read-only.
These include local inspection and known network reads. Commands that can write
files are classified by their selected form, so an export to stdout may be
read-only while the same command with a file option requires write access.

Known dry-run forms are read-only when the installed command parser supports
the dry-run option. Tool annotations describe the broadest behavior of a tool,
which can be more restrictive than one particular invocation.

## Two explicit capabilities

`--allow-write` permits mutations of conda-managed environments, packages,
configuration, caches, and files. `--allow-exec` permits arbitrary process
paths such as `conda run`, opaque passthrough arguments, and raw argv.

The capabilities are independent. A raw mutation needs both because the call
uses arbitrary argv and changes state. `conda run` needs process execution but
does not inherently need conda write access.

Unknown commands fail closed as mutations. Opaque plugin passthrough commands
also require process execution authority.

## Enforcement and redaction

Policy is an immutable value created at server startup. The server classifies
the compiled argv and rejects missing authority before the child process is
created. MCP annotations are hints for clients, not access controls.

Error responses avoid reflecting submitted argument values, command output,
credentials, headers, or complete environments. The capabilities resource
contains executable and plugin metadata, but no authentication objects or
request headers.

## Operational limits

Time, standard input, standard output, and standard error are bounded. A raw
request may shorten but cannot raise the startup timeout. The server drains
both output streams to avoid deadlock, retains only the configured number of
bytes, and reports truncation. UTF-8 output is cut at a character boundary.

There is no interactive terminal and no shell evaluation. These constraints
reduce ambiguity, but they do not make an allowed conda operation harmless.
Run the MCP server with the least authority its client needs.
