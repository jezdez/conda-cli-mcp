# AGENTS.md — conda-cli-mcp coding guidelines

## Project contract

- The repository, distribution, and console command are named
  `conda-cli-mcp`. The Python package is `conda_cli_mcp`.
  `conda-mcp` is reserved for the future umbrella package that brings
  `conda-cli-mcp` and `conda-meta-mcp` together.

- The server exposes the CLI accepted by the configured conda
  executable, including subcommands contributed through conda plugin
  hooks.

- Every CLI operation must remain reachable through a raw argv tool.
  Commands with introspectable argparse definitions also receive
  generated structured tools.

- Discover the command catalog once at server startup. Keep the MCP
  tool list stable for that server lifetime. Installing, removing, or
  updating a plugin reports that a restart is required.

- Run conda commands out of process. Conda owns parser dispatch,
  configuration loading, plugin ordering, command hooks, solver hooks,
  transaction hooks, reporters, authentication, and exception
  handling.

- Do not expose every conda plugin hook as an independent MCP tool.
  Non-command hooks participate through normal conda execution.

- Optional plugin integrations must run through public interfaces in
  the target interpreter. Do not duplicate a plugin's cache format,
  path resolution, or validation in the MCP server.

- Shell commands may return activation code or environment changes.
  Never claim to mutate the shell of the MCP host.

## Project structure

- Keep the package flat until a real grouping requires a subpackage.

- `server.py` owns MCP capabilities, tool listing, and dispatch.

- `discovery.py` owns argparse traversal and conversion into the public
  command catalog.

- `execution.py` owns argv construction, subprocess lifetime,
  cancellation, and output capture.

- `models.py` owns command, argument, execution result, and policy
  value objects.

- `cli.py` owns server command-line parsing and startup.

- `__main__.py` is a thin entry point.

- Tests mirror source modules. Tests for
  `conda_cli_mcp/discovery.py` live in `tests/test_discovery.py`.

- Do not commit generated tool catalogs. Generate them from the target
  conda installation at runtime.

## Imports and dependencies

- Use relative imports for intra-package references. Absolute
  `conda_cli_mcp.*` imports belong in tests and entry points.

- Keep imports at module scope. Use lazy imports only for optional
  dependencies or a measured startup boundary.

- Minimize the dependency graph. Prefer the standard library and
  already-required packages.

- Pin minimum supported versions in `pyproject.toml`, not exact
  versions.

- Use pixi for development and dependency management. Do not use
  direct `pip install` commands for repository development.

## Public Python interfaces

- Use `from __future__ import annotations` in every module.

- Use modern annotations such as `str | None`, `list[str]`,
  `collections.abc`, `pathlib.Path`, and `enum.StrEnum` where the
  supported Python versions allow it.

- Prefer immutable, typed value objects for discovered commands,
  arguments, policies, and execution results. Do not pass mutable
  argparse objects beyond the discovery adapter.

- Do not scatter private module-level helpers. Before adding `_foo`,
  check in this order:

  1. Use a public interface already provided by Python, conda, or an
     existing dependency.
  2. Put behavior that belongs to an existing value object on that
     object as a public method.
  3. Make genuinely reusable logic a public function with a clear
     name and docstring.
  4. Inline logic used at only one call site.

- Do not introduce an abstract base class, protocol, factory, or
  registry for one implementation. Add an interface when there is a
  real second implementation or external integration boundary.

- Do not call underscore-prefixed conda attributes, methods, or
  helpers from feature modules. If required CLI parity has no public
  conda interface, isolate the access in one compatibility adapter,
  document the supported conda versions and reason, and cover it with
  a focused test.

- Argparse has no public command-tree inspection interface.
  `discovery.py` is the only module allowed to inspect argparse
  internals. It must immediately convert them into public immutable
  models. No other module may depend on private argparse state.

- Do not use section comments to group code. Split a module when its
  responsibilities need section headings.

- Comments explain non-obvious intent, constraints, or compatibility
  decisions. Do not narrate the code.

## Conda discovery and execution

- Resolve the target conda executable explicitly. Do not assume the
  server process and target conda installation share an environment.

- Perform parser discovery in a short-lived helper process associated
  with the target conda installation. Do not retain conda global
  context or plugin objects in the MCP server.

- Prefer public conda APIs when discovery requires conda behavior.
  Do not reimplement conda configuration, platform detection, plugin
  loading, or command dispatch.

- Convert structured tool arguments back into argv and validate that
  argv with the target parser where possible.

- Preserve argparse declaration order, positional order, repeated
  options, mutually exclusive groups, aliases, `--`, and greedy
  plugin arguments.

- Canonical leaf commands receive deterministic tool names. Aliases
  are catalog metadata, not duplicate tools.

- Unsupported or opaque parser actions fall back to an explicit argv
  array. Never silently omit a command or argument.

- Generated tools and the raw argv tool use the same execution path
  and result type.

- Execute with `asyncio.create_subprocess_exec` and argv lists. Never
  invoke a shell.

- Parse stdout as JSON only when it contains exactly one complete JSON
  document. Preserve the original stdout and stderr in the result.

## MCP behavior

- Use the official MCP Python SDK and its public APIs.

- Generated JSON Schemas must describe required values, enums, arrays,
  booleans, counts, and mutually exclusive groups as precisely as the
  installed parser allows.

- Return one consistent execution result containing exit code, stdout,
  stderr, duration, parsed JSON when available, timeout state,
  cancellation state, truncation indicators, and restart requirement.

- Capability metadata must report the target conda executable,
  version, command catalog, and installed plugin distributions without
  exposing credentials, authentication objects, or request headers.

- Keep tool descriptions factual and concise. Describe mutation and
  arbitrary command execution directly.

## Safety

- Read-only execution is the default policy.

- Mutating commands require explicit startup enablement.

- `conda run`, opaque argv execution, and other arbitrary process
  paths require separate explicit startup enablement.

- Policy is immutable for the server lifetime and is enforced before
  spawning the process. Tool annotations are descriptive, not the
  enforcement mechanism.

- Serialize conda executions initially. Revisit concurrency only with
  evidence that independent operations and prefix mutations can be
  separated safely.

- Bound execution time and captured output. Report truncation rather
  than consuming unbounded memory.

- Cancellation must terminate the process tree, wait for a bounded
  grace period, then kill it if necessary. Do not leave descendant
  processes running.

- Never log complete environments, credentials, tokens, authentication
  headers, or unredacted command output that may contain secrets.

## Testing

- Tests are plain pytest functions. Do not use class-based test
  grouping.

- Never use `unittest.mock`, `MagicMock`, `Mock`, or `patch`. Use
  pytest fixtures, `monkeypatch`, recording closures, and small real
  fakes.

- Use `pytest.mark.parametrize` for command and argparse action
  matrices. Add cases to an existing matrix before creating another
  test function.

- Put shared setup in fixtures at the narrowest useful
  `conftest.py`.

- Test the public models and interfaces. Do not make tests depend on
  private helper functions.

- Maintain fixture plugins for a nested configured subcommand and an
  opaque greedy subcommand. Exercise non-command plugin hooks through
  real conda subprocess execution.

- Compare raw argv and generated-tool behavior for representative
  built-in and plugin commands.

- Cover Linux, macOS, and Windows behavior, JSON output, cancellation,
  timeouts, output limits, redaction, plugin restart requirements,
  `--no-plugins`, shell commands, and competing prefix mutations.

- After code changes, run `pixi run test` and `pixi run check`.

## Lockfile maintenance

- After changes to project dependencies, features, tasks, or workspace
  settings, run `pixi lock` and commit the updated `pixi.lock`.

## Documentation

- Use Sphinx with `conda-sphinx-theme`, MyST, and sphinx-design when
  documentation is introduced.

- Follow Diataxis for tutorials, how-to guides, reference, and
  explanation.

- Document reachability, discoverability, plugin participation, safety
  policy, shell limitations, restart behavior, and supported conda
  versions explicitly.

## Pull requests and releases

- Use the repository's native pull request title style. Never prefix a
  title with `[codex]`.

- Write pull request and issue bodies as one line per paragraph or
  bullet. Let GitHub wrap prose.

- Do not include validation steps, test commands, or verification
  output in pull request descriptions.

- Never create or push tags, create releases, or publish packages
  without explicit user approval.

- Never use semicolons in prose.
