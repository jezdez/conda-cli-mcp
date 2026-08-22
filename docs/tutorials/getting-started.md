# Connect a read-only conda server

This tutorial runs `conda-cli-mcp` from its source checkout, connects a generic
stdio MCP client, and inspects the tools discovered from the target conda
installation.

## Prerequisites

- Git
- [Pixi](https://pixi.sh/)
- an MCP client that can start a local stdio server
- a target conda version in the supported `>=26.7,<27` range

## Prepare the server

Clone the repository and install its locked development environment:

```console
git clone https://github.com/jezdez/conda-cli-mcp.git
cd conda-cli-mcp
pixi install --locked
```

Confirm the server and target conda are available:

```console
pixi run conda-cli-mcp --version
pixi run conda --version
```

Find the absolute executable paths that the MCP client will use:

```console
pixi run python -c "import shutil; print(shutil.which('conda-cli-mcp'))"
pixi run python -c "import shutil; print(shutil.which('conda.exe') or shutil.which('conda'))"
```

On Windows, select `conda.exe`. Batch launchers ending in `.bat` or `.cmd` are
not supported.

## Configure the MCP client

Add a stdio server entry using the two paths from the previous step:

```json
{
  "mcpServers": {
    "conda": {
      "command": "/absolute/path/to/conda-cli-mcp",
      "args": ["--conda-exe", "/absolute/path/to/conda"]
    }
  }
}
```

The surrounding configuration and restart procedure depend on the client. Keep
the server arguments read-only for this first connection.

## Inspect the discovered interface

Start or restart the MCP client, then list the server's tools. The list should
contain generated tools such as `conda_info`. Exact tools depend on the target
conda installation and its installed plugins.

Read the `conda://capabilities` resource. Confirm that:

- `target_executable` is the selected conda path
- `conda_version` is in the supported range
- `generated_tools` contains the structured tool names
- `plugins` describes external conda entry points visible at startup

The resource also contains the immutable startup command catalog and a
discovery fingerprint.

## Run a read-only tool

Call `conda_info` with an empty input object:

```json
{}
```

The result contains a short text summary and structured fields. A successful
call has `exit_code` set to `0`, preserves conda's output in `stdout`, and sets
`parsed_json` when stdout is exactly one complete JSON document.

Mutation tools can still appear in the list. The default policy rejects their
execution before conda starts.

## Next steps

- [Configure the server](../how-to/configure-the-server.md) for another conda
  installation or different resource limits.
- [Enable operations](../how-to/enable-operations.md) only when the client
  needs write or process execution access.
- Read the [MCP interface reference](../reference/mcp-interface.md) for the
  complete resource, tool, and result contracts.
