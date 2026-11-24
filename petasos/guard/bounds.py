"""Shared recognition work bounds.

Recognition reads every command in the text; its cost is linear in the
text's length. These bound how deep it follows text inside text. Text past
a bound is never silently allowed: it is reported as a change.
"""

from __future__ import annotations

# Scripts handed to a shell, ``eval`` or Python, and commands started by
# another command, are followed this many levels deep.
_MAX_DEPTH = 3
# Quoted text inside quoted text is read this many levels deep.
_MAX_QUOTE_DEPTH = 32
# The words after each program word or verb that starts a match in the
# reading of quoted text, summed over the whole text (see ``_quoted_hit``).
_WORD_BUDGET = 100_000
