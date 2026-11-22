"""Optional dependencies, imported only by the features that need them.

The default install covers the SBEM components, the archetype model and the builder
(`epinterface.sbem.builder.Model`). Other features need an extra:

- ``geo``: neighbour shading from building footprints (shapely, geopandas).
- ``prisma``: the SBEM component database and its Excel loader (prisma, openpyxl).
- ``comfort``: the SET-based overheating metrics (pythermalcomfort).
"""

from __future__ import annotations

import importlib
from types import ModuleType


class MissingOptionalDependencyError(ImportError):
    """An optional dependency of epinterface is not installed."""


def missing(module: str, extra: str, feature: str | None = None) -> ImportError:
    """Build the error raised when an optional module cannot be imported.

    Args:
        module (str): The module that failed to import, e.g. ``"shapely"``.
        extra (str): The epinterface extra that provides it, e.g. ``"geo"``.
        feature (str | None): What needs the module, used in the error message.

    Returns:
        error (MissingOptionalDependencyError): The error to raise.
    """
    top = module.split(".")[0]
    what = feature or "this feature of epinterface"
    msg = (
        f"{what} needs the optional dependency '{top}', which is not installed. "
        f"Install it with: pip install 'epinterface[{extra}]'"
    )
    return MissingOptionalDependencyError(msg)


def require(module: str, extra: str, feature: str | None = None) -> ModuleType:
    """Import an optional module, or fail with an error naming the extra to install.

    Args:
        module (str): The module to import, e.g. ``"shapely"``.
        extra (str): The epinterface extra that provides it, e.g. ``"geo"``.
        feature (str | None): What needs the module, used in the error message.

    Returns:
        module (ModuleType): The imported module.

    Raises:
        MissingOptionalDependencyError: If the module cannot be imported.
    """
    try:
        return importlib.import_module(module)
    except ImportError as e:
        raise missing(module, extra, feature) from e
