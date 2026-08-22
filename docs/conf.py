"""Sphinx configuration for conda-cli-mcp documentation."""

from __future__ import annotations

project = html_title = "conda-cli-mcp"
copyright = "2026, Jannis Leidel"
author = "Jannis Leidel"

extensions = [
    "myst_parser",
    "sphinx_design",
]

myst_enable_extensions = ["colon_fence"]

html_theme = "conda_sphinx_theme"

html_theme_options = {
    "icon_links": [
        {
            "name": "GitHub",
            "url": "https://github.com/jezdez/conda-cli-mcp",
            "icon": "fa-brands fa-square-github",
            "type": "fontawesome",
        },
    ],
}

html_context = {
    "github_user": "jezdez",
    "github_repo": "conda-cli-mcp",
    "github_version": "main",
    "doc_path": "docs",
}

html_baseurl = "https://jezdez.github.io/conda-cli-mcp/"
exclude_patterns = ["_build"]
