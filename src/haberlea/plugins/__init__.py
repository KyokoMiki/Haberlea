"""Plugin system for Haberlea using entry points.

This module provides the plugin discovery and loading mechanism using
Python's entry points system (PEP 621).

Entry point groups:
    - haberlea.modules: Music service modules (Qobuz, Tidal, etc.)
    - haberlea.extensions: Post-download extensions (upload, torrent, etc.)

Example pyproject.toml for a module plugin:
    [project.entry-points."haberlea.modules"]
    qobuz = "haberlea.modules.qobuz:module_information"

Example pyproject.toml for an extension plugin:
    [project.entry-points."haberlea.extensions"]
    alist = "haberlea_alist:extension_settings"
"""

from .base import ExtensionBase, ModuleBase
from .loader import (
    discover_extensions,
    discover_modules,
    load_extension,
    load_module,
)

__all__ = [
    "ExtensionBase",
    "ModuleBase",
    "discover_extensions",
    "discover_modules",
    "load_extension",
    "load_module",
]
