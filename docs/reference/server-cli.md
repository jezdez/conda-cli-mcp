# Server command-line reference

`conda-cli-mcp` starts one MCP server over standard input and standard output.

## Usage

```text
conda-cli-mcp [--conda-exe PATH] [--timeout SECONDS]
              [--output-limit-bytes BYTES] [--stdin-limit-bytes BYTES]
              [--allow-write] [--allow-exec] [--version]
```

## Options

| Option | Default | Meaning |
| --- | --- | --- |
| `--conda-exe PATH` | `CONDA_EXE`, then `PATH` | Target conda executable |
| `--timeout SECONDS` | `900` | Finite positive maximum timeout for discovery and execution |
| `--output-limit-bytes BYTES` | `1048576` | Positive retained-byte limit for each output stream |
| `--stdin-limit-bytes BYTES` | `1048576` | Positive UTF-8 byte limit for raw-tool input |
| `--allow-write` | disabled | Permit operations classified as mutations |
| `--allow-exec` | disabled | Permit arbitrary execution and expose `conda_execute` |
| `--version` | | Print the server version and exit |

The selected target must be a file. Windows batch launchers are rejected, so
select `conda.exe` directly.

## Startup behavior

At startup the server:

1. runs `conda info --json` against the target
2. discovers the target argparse command tree in a short-lived helper process
3. discovers external conda plugin entry points
4. creates an immutable tool catalog and capabilities resource
5. begins MCP stdio transport

The currently supported target conda range is `>=26.7,<27`.
