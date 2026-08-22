# Enable write and process execution

Start the server with only the authority required by the MCP client. Policy is
immutable for the server lifetime and is enforced before spawning conda.

## Permit conda-managed mutations

Enable environment, package, configuration, cache, and file mutations:

```console
ccm \
  --conda-exe /absolute/path/to/conda \
  --allow-write
```

Generated mutation tools remain visible without this option, but calls are
rejected. Known dry-run forms are treated as read-only where conda's parser
supports them.

## Permit arbitrary process paths

Enable `conda run` and expose the raw argv tool:

```console
ccm \
  --conda-exe /absolute/path/to/conda \
  --allow-exec
```

`--allow-exec` makes `conda_execute` discoverable. Raw argv is still
classified. A known read-only raw command needs only `--allow-exec`, while a
mutation or unknown command also needs `--allow-write`.

## Permit both capabilities

Use both options when the client must invoke arbitrary or opaque operations
that may also mutate state:

```console
ccm \
  --conda-exe /absolute/path/to/conda \
  --allow-write \
  --allow-exec
```

Typical requirements are:

| Operation | Required startup options |
| --- | --- |
| Generated read-only command | none |
| Generated mutation | `--allow-write` |
| `conda run` | `--allow-exec` |
| Raw read-only argv | `--allow-exec` |
| Raw mutation or unknown argv | `--allow-write`, `--allow-exec` |
| Opaque plugin passthrough that may mutate | `--allow-write`, `--allow-exec` |

MCP tool annotations report the broadest known risk of each tool. They help
clients present appropriate controls, but server-side policy remains the
enforcement mechanism.

Restart the server after changing startup options. See
[the safety model](../explanation/safety.md) for the classification rules and
their limits.
