"""Prop Material Creator - Karma material builder for single FBX props."""

__version__ = "1.3.0"

from . import core   # noqa: F401
from . import ui     # noqa: F401


def show():
    """Convenience entry so the shelf can call prop_material_creator.show()."""
    return ui.show()
