"""Haberlea - A modular music downloader with plugin support."""

__version__ = "0.1.0"
__author__ = "KyokoMiki"
__description__ = "A modular music downloader with plugin support"

from .cli import main
from .core import Haberlea, haberlea_core_download

__all__ = [
    "main",
    "Haberlea",
    "haberlea_core_download",
    "__version__",
    "__author__",
    "__description__",
]
