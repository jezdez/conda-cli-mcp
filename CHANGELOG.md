# Changelog

All notable changes to conda-cli-mcp will be documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/).

## Unreleased

## 0.1.0 — 2026-08-22

### Added

- Added startup discovery of built-in and plugin-contributed conda commands,
  with structured MCP tools generated from representable argparse definitions
  and optional raw argv access to the complete command line.
- Added a read-only-by-default policy with separate startup controls for conda
  mutations and arbitrary process execution.
- Added bounded, serialized out-of-process conda execution with timeouts,
  cancellation, output truncation, JSON detection, and process-tree cleanup on
  Linux, macOS, and Windows.
- Added the `conda://capabilities` resource with the target conda version,
  command catalog, plugin inventory, and restart detection.
- Added optional read-only command metadata from conda-completion 0.3 or newer
  through its public Python API.
- Added Sphinx documentation, a noarch conda recipe, and PyPI trusted
  publishing automation.
