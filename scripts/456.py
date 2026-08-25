"""
456.py - runs on Houdini startup (after the UI is up) for this package.
Registers the Prop Material Creator button on the shared CGA Tools shelf.

Houdini executes scripts/456.py for every package on its path. Registration is
idempotent, so running it again on the next launch is harmless.
"""

try:
    from prop_material_creator import shelf_register
    shelf_register.register()
except Exception as _e:
    import sys
    sys.stderr.write("Prop Material Creator: shelf registration failed: %s\n" % _e)
