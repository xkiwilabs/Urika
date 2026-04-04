"""Backward-compat shim — makes urika.repl_session an alias for urika.repl.session."""

import importlib
import sys

_real = importlib.import_module("urika.repl.session")
sys.modules[__name__] = _real
