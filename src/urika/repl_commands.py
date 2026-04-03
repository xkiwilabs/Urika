"""Backward-compat shim — makes urika.repl_commands an alias for urika.repl.commands.

By replacing sys.modules['urika.repl_commands'] with the actual module,
all patch() calls and attribute lookups against the old path work correctly.
"""

import importlib
import sys

# Ensure the real module is loaded
_real = importlib.import_module("urika.repl.commands")

# Replace this shim module with the real one in sys.modules
sys.modules[__name__] = _real
