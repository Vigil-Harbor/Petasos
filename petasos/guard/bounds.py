"""Shared recognition work bounds.

Recognition reads every command in the text; its cost is linear in the
text's length. These bound how deep it follows text inside text. Text past
a bound is never silently allowed: it is reported as a change.
"""

from __future__ import annotations

# Scripts handed to a shell, ``eval`` or Python, and commands started by
# another command, are followed this many levels deep.
_MAX_DEPTH = 3
