"""The Petasos tab's API, served by Hermes's dashboard.

``build_router`` is what the plugin directory imports. The functions that
build each response take plain values and return plain values. They do not
import a web framework, and this package holds no process-wide state.
"""

from petasos.hermes.dashboard.errors import API_VERSION
from petasos.hermes.dashboard.router import build_router

__all__ = ["API_VERSION", "build_router"]
