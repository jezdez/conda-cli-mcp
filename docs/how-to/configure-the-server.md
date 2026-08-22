# Configure the server

Use startup options to select the target conda installation and bound each
child process. These settings remain fixed until the MCP server restarts.

## Select conda explicitly

Pass an executable path when the MCP server and target conda live in different
environments:

```console
conda-cli-mcp --conda-exe /absolute/path/to/conda
```

Resolution follows this order:

1. the value passed to `--conda-exe`
2. the `CONDA_EXE` environment variable
3. `conda` found on `PATH`

GUI-launched clients often receive a smaller `PATH` than an interactive shell.
Prefer an absolute path in client configuration. On Windows, point to
`conda.exe` instead of a `.bat` or `.cmd` launcher.

## Set time and data limits

The default timeout is 900 seconds. The server retains at most 1 MiB from each
output stream and accepts at most 1 MiB of raw-tool input.

Set different positive limits at startup:

```console
conda-cli-mcp \
  --conda-exe /absolute/path/to/conda \
  --timeout 120 \
  --output-limit-bytes 2097152 \
  --stdin-limit-bytes 65536
```

`--output-limit-bytes` applies separately to standard output and standard
error. The child process is still drained after the retained limit is reached.
The result marks each truncated stream independently.

The raw `conda_execute` tool may shorten the timeout for one call, but cannot
raise the server limit. Generated tools use the server limit. Oversized input
and invalid working directories are rejected before conda starts.

## Account for process limitations

The server passes argv directly to conda without a shell. Shell interpolation,
pipes, redirection, aliases, and shell functions are unavailable.

The server does not allocate an interactive terminal. Use conda's
noninteractive flags for commands that could prompt. Only the raw tool accepts
bounded standard input and a working directory.

Activation commands can return shell code or environment changes, but cannot
modify the MCP host application's shell. The client must apply returned changes
in its own shell process.

See the [server CLI reference](../reference/server-cli.md) for every option.
