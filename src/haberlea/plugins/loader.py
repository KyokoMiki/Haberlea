"""Plugin discovery and loading using entry points.

This module provides functions to discover and load plugins registered
via Python entry points (PEP 621).
"""

import importlib
import logging
from importlib.metadata import entry_points
from typing import TYPE_CHECKING

from haberlea.plugins.base import ExtensionBase, ModuleBase

if TYPE_CHECKING:
    from haberlea.utils.models import ExtensionInformation, ModuleInformation

logger = logging.getLogger(__name__)

# Entry point group names
MODULES_GROUP = "haberlea.modules"
EXTENSIONS_GROUP = "haberlea.extensions"


def discover_modules() -> dict[str, ModuleInformation]:
    """Discover all installed module plugins.

    Scans entry points in the 'haberlea.modules' group and loads
    their module_information objects.

    Returns:
        Dictionary mapping module names to their ModuleInformation.

    Example:
        >>> modules = discover_modules()
        >>> print(modules.keys())
        dict_keys(['qobuz', 'tidal', 'deezer'])
    """
    modules: dict[str, ModuleInformation] = {}

    eps = entry_points(group=MODULES_GROUP)
    for ep in eps:
        try:
            module_info = ep.load()
            modules[ep.name] = module_info
            logger.debug(f"Discovered module: {ep.name}")
        except Exception as e:
            logger.error(f"Failed to load module '{ep.name}': {e}")

    return modules


def discover_extensions() -> dict[str, ExtensionInformation]:
    """Discover all installed extension plugins.

    Scans entry points in the 'haberlea.extensions' group and loads
    their extension_settings objects.

    Returns:
        Dictionary mapping extension names to their ExtensionInformation.

    Example:
        >>> extensions = discover_extensions()
        >>> print(extensions.keys())
        dict_keys(['alist', 'baidunetdisk'])
    """
    extensions: dict[str, ExtensionInformation] = {}

    eps = entry_points(group=EXTENSIONS_GROUP)
    for ep in eps:
        try:
            ext_info = ep.load()
            extensions[ep.name] = ext_info
            logger.debug(f"Discovered extension: {ep.name}")
        except Exception as e:
            logger.error(f"Failed to load extension '{ep.name}': {e}")

    return extensions


def load_module(module_name: str) -> type | None:
    """Load a module's interface class by name.

    Finds the class that inherits from ModuleBase in the module.

    Args:
        module_name: Name of the module to load.

    Returns:
        The ModuleBase subclass, or None if not found.

    Example:
        >>> ModuleClass = load_module('qobuz')
        >>> module = ModuleClass(controller)
    """
    eps = entry_points(group=MODULES_GROUP)
    for ep in eps:
        if ep.name == module_name:
            try:
                ep.load()
                module_pkg = ep.value.rsplit(":", 1)[0]
                interface_module = importlib.import_module(module_pkg)
                # Find class that inherits from ModuleBase
                for name in dir(interface_module):
                    obj = getattr(interface_module, name)
                    if (
                        isinstance(obj, type)
                        and issubclass(obj, ModuleBase)
                        and obj is not ModuleBase
                    ):
                        return obj
            except Exception as e:
                logger.error(f"Failed to load module interface '{module_name}': {e}")
                return None
    return None


def load_extension(extension_name: str) -> type | None:
    """Load an extension's class by name.

    Finds the class that inherits from ExtensionBase in the module.

    Args:
        extension_name: Name of the extension to load.

    Returns:
        The ExtensionBase subclass, or None if not found.

    Example:
        >>> ExtClass = load_extension('archiver')
        >>> ext = ExtClass(settings)
    """
    eps = entry_points(group=EXTENSIONS_GROUP)
    for ep in eps:
        if ep.name == extension_name:
            try:
                ep.load()
                module_pkg = ep.value.rsplit(":", 1)[0]
                interface_module = importlib.import_module(module_pkg)
                # Find class that inherits from ExtensionBase
                for name in dir(interface_module):
                    obj = getattr(interface_module, name)
                    if (
                        isinstance(obj, type)
                        and issubclass(obj, ExtensionBase)
                        and obj is not ExtensionBase
                    ):
                        return obj
            except Exception as e:
                logger.error(f"Failed to load extension class '{extension_name}': {e}")
                return None
    return None


def get_module_entry_point(module_name: str) -> str | None:
    """Get the entry point value for a module.

    Args:
        module_name: Name of the module.

    Returns:
        The entry point value string, or None if not found.
    """
    eps = entry_points(group=MODULES_GROUP)
    for ep in eps:
        if ep.name == module_name:
            return ep.value
    return None


def get_extension_entry_point(extension_name: str) -> str | None:
    """Get the entry point value for an extension.

    Args:
        extension_name: Name of the extension.

    Returns:
        The entry point value string, or None if not found.
    """
    eps = entry_points(group=EXTENSIONS_GROUP)
    for ep in eps:
        if ep.name == extension_name:
            return ep.value
    return None
