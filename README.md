# conda-cli-mcp

`conda-cli-mcp` exposes an installed conda command line through the Model
Context Protocol. It discovers built-in and plugin-contributed commands at
startup, creates structured tools from conda's argparse definitions, and keeps
the complete CLI reachable through an explicitly enabled raw argv tool.

The server runs conda in bounded child processes. Conda remains responsible
for configuration, plugin ordering, solving, transactions, reporters,
authentication, hooks, and error handling.

When `conda-completion` 0.3 or newer is installed in the target environment, a
read-only metadata tool exposes its command-specific completion hints through
the plugin's public Python API.

The project is under active development and is not published yet. It supports
target conda versions `>=26.7,<27`.

## Documentation

The [documentation](docs/index.md) is organized by purpose:

- [Tutorial](docs/tutorials/getting-started.md)
- [How-to guides](docs/how-to/configure-the-server.md)
- [Reference](docs/reference/server-cli.md)
- [Explanation](docs/explanation/architecture.md)

The published site will live at
[jezdez.github.io/conda-cli-mcp](https://jezdez.github.io/conda-cli-mcp/).

## Safety

The default policy is read-only. `--allow-write` permits conda-managed
mutations. `--allow-exec` permits `conda run`, opaque passthrough arguments,
and the raw `conda_execute` tool. Policy is fixed at startup and enforced
before conda starts.

## Running the server

Select the target conda executable explicitly when it lives in another
environment:

```console
conda-cli-mcp --conda-exe /absolute/path/to/conda
```

Without `--conda-exe`, resolution checks `CONDA_EXE` and then `PATH`. MCP
clients connect over standard input and standard output. See the
[getting-started tutorial](docs/tutorials/getting-started.md) for a client
configuration.

## Project scope

- `conda-cli-mcp` owns local conda CLI discovery and execution.
- [`conda-meta-mcp`](https://github.com/conda-incubator/conda-meta-mcp) owns
  read-only package and ecosystem metadata.
- `conda-mcp` is reserved for a future umbrella package that installs both.

## Development

Development, documentation, and packaging use [Pixi](https://pixi.sh/):

```console
pixi install
pixi run test
pixi run check
pixi run -e docs docs
pixi run -e build package
```

The conda recipe is noarch Python and lives in `recipe/recipe.yaml`.
