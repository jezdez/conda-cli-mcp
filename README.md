# conda-cli-mcp

`conda-cli-mcp` exposes the CLI of an installed conda distribution through the
Model Context Protocol. It discovers built-in and plugin-contributed commands
from conda's argparse tree, generates structured MCP tools where the parser is
introspectable, and retains a raw argv path for complete CLI reachability.

The server runs every conda command in a fresh child process. Conda remains
responsible for configuration, plugin ordering, solving, transactions,
reporting, authentication, and error handling.

## Project boundaries

- `conda-cli-mcp` owns local CLI discovery and execution.
- [`conda-meta-mcp`](https://github.com/conda-incubator/conda-meta-mcp) owns
  read-only package and ecosystem metadata.
- `conda-mcp` is reserved for a future umbrella package.

## Safety contract

The default server policy is read-only. Mutating commands and arbitrary
execution paths such as `conda run` require explicit startup enablement. Tool
annotations describe risk, while the server policy enforces it before a child
process starts.

Shell activation is returned as shell code or environment changes. An MCP
server cannot mutate its host application's shell.

## Development

Development uses [pixi](https://pixi.sh/):

```shell
pixi install
pixi run test
pixi run check
```

The package is under active development and is not published yet.

## Independent implementation

This project is independently designed from conda's public interfaces,
Python's argparse behavior, the MCP specification, and public interoperability
documentation.
