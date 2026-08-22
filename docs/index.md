# conda-cli-mcp

`conda-cli-mcp` exposes the command line of one installed conda through the
Model Context Protocol (MCP). It discovers conda and plugin commands at server
startup, generates structured tools where argparse metadata is sufficient, and
keeps every command reachable through raw argv when explicitly enabled.

Conda still performs configuration loading, plugin ordering, solving,
transactions, authentication, command hooks, and error handling. The MCP
server runs conda in bounded child processes without invoking a shell.

:::{note}
This project is alpha software.
:::

## Choose a documentation path

::::{grid} 2
:gutter: 3

:::{grid-item-card} {octicon}`rocket` Tutorial
:link: tutorials/getting-started
:link-type: doc

Connect an MCP client to a read-only server and inspect the discovered conda
interface.
:::

:::{grid-item-card} {octicon}`tools` How-to guides
:link: how-to/install-with-conda
:link-type: doc

Install from Anaconda.org, select a target conda, set limits, enable
operations, and refresh tools after plugin changes.
:::

:::{grid-item-card} {octicon}`list-unordered` Reference
:link: reference/server-cli
:link-type: doc

Look up server options, MCP tools, resources, schemas, and result fields.
:::

:::{grid-item-card} {octicon}`book` Explanation
:link: explanation/architecture
:link-type: doc

Understand parser discovery, process isolation, plugin participation, and the
safety model.
:::

::::

## Supported target

The server requires Python 3.10 or newer and is tested on Linux, macOS, and
Windows. The selected target must provide conda `>=26.7,<27`. The server and
target conda installation may live in different Python environments when
`--conda-exe` identifies the target explicitly.

```{toctree}
:hidden:
:caption: Tutorial

tutorials/getting-started
```

```{toctree}
:hidden:
:caption: How-to guides

how-to/configure-the-server
how-to/install-with-conda
how-to/enable-operations
how-to/refresh-plugin-tools
```

```{toctree}
:hidden:
:caption: Reference

reference/server-cli
reference/mcp-interface
```

```{toctree}
:hidden:
:caption: Explanation

explanation/architecture
explanation/safety
```

```{toctree}
:hidden:
:caption: Project

changelog
```
