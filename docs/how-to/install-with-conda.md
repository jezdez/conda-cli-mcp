# Install with conda

Install the conda package into a dedicated server environment or into the
environment containing the conda installation you want to expose.

With `ccm`, the server environment and the target conda installation can be
separate. The server process owns its Python dependencies. `--conda-exe`
selects the conda whose commands and plugins the server exposes.

The `ccm` and `conda mcp` launchers require `conda-cli-mcp` 0.2.0 or newer.
The version constraints below prevent the incompatible 0.1.0 command from
being installed with this guide.

## Install from Anaconda.org

Create a dedicated server prefix from the [`jezdez` channel on
Anaconda.org](https://anaconda.org/jezdez/conda-cli-mcp) and `conda-forge`.

::::{tab-set}
:::{tab-item} POSIX

```console
server_prefix="$HOME/.local/share/conda-cli-mcp"
conda create --yes --no-default-packages \
  --prefix "$server_prefix" \
  --override-channels \
  --channel jezdez \
  --channel conda-forge \
  "conda-cli-mcp>=0.2"
"$server_prefix/bin/ccm" --version
```

:::
:::{tab-item} PowerShell

```powershell
$serverPrefix = Join-Path $env:LOCALAPPDATA "conda-cli-mcp"
conda create --yes --no-default-packages `
  --prefix $serverPrefix `
  --override-channels `
  --channel jezdez `
  --channel conda-forge `
  "conda-cli-mcp>=0.2"
& (Join-Path $serverPrefix "Scripts\ccm.exe") --version
```

:::
::::

Use the absolute `ccm` path directly as the MCP client command. Direct
execution avoids the default output capture and extra process introduced by
`conda run`.

## Install with conda-global

Install `ccm` as an isolated PATH tool when conda-global is available:

```console
conda global install "conda-cli-mcp>=0.2" --environment conda-cli-mcp --expose ccm --override-channels --channel jezdez --channel conda-forge
ccm --version
```

conda-global exposes the `ccm` console command through its trampoline. Its
isolated tool environment is not part of the host conda interpreter, so this
installation does not add `conda mcp` to the host conda.

## Use the conda plugin command

When `conda-cli-mcp` is installed in conda's own environment, it registers the
`conda mcp` subcommand:

```console
conda mcp --version
```

`conda mcp` targets the conda installation that loaded the plugin. You do not
need to pass `--conda-exe`. External plugins, including this command, are
unavailable when conda starts with `--no-plugins`.

## Configure the MCP client

For a separate server environment, use the absolute path to `ccm` and point
`--conda-exe` at the target conda installation:

```json
{
  "mcpServers": {
    "conda": {
      "command": "/absolute/path/to/ccm",
      "args": ["--conda-exe", "/absolute/path/to/target/conda"]
    }
  }
}
```

For a same-environment installation such as a future conda-runtime bundle, use
that conda executable and the `mcp` subcommand:

```json
{
  "mcpServers": {
    "conda": {
      "command": "/absolute/path/to/conda",
      "args": ["mcp"]
    }
  }
}
```

On Windows, the conda executable must be `conda.exe`, not a `.bat` or `.cmd`
wrapper.
