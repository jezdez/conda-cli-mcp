# Refresh tools after plugin changes

The generated tool list and `conda://capabilities` resource are snapshots from
server startup. Restart the server after installing, removing, or updating a
conda plugin.

## Detect a required restart

After a successful write or arbitrary execution, inspect the structured result:

```json
{
  "restart_required": true
}
```

The server compares the current conda version and external plugin entry-point
metadata with the startup fingerprint. It also requests a restart
conservatively when that post-operation inspection fails.

The running tool list does not change even after `restart_required` becomes
true.

## Restart and verify

1. Stop the current MCP server through the client.
2. Start it again with the same target conda executable and policy options.
3. List tools again.
4. Read `conda://capabilities` and confirm the plugin metadata and discovery
   fingerprint changed as expected.

Commands contributed through conda's subcommand hook receive structured tools
when their argparse definitions are representable. Opaque commands remain
reachable through `conda_execute` when `--allow-exec` is enabled.

Passing conda's `--no-plugins` option affects that individual conda process. It
does not rebuild the server's startup catalog.
