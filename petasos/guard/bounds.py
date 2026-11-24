"""Shared recognition work bounds.

Recognition reads every command in the text; its cost is linear in the
text's length. These bound how deep it follows text inside text, and how
much work one recognition may do. Text past a bound is never silently
allowed: it is reported as a change.
"""

from __future__ import annotations

from dataclasses import dataclass

# Text inside text is followed this many levels deep. One count runs through
# every step into nested text: a script handed to a shell, ``eval``, Python,
# PowerShell or cmd, a command string inside program text, a here-document
# read as a program, ``Invoke-Expression``, and a command another starts.
_MAX_DEPTH = 3
# The reading of quoted text continues the same count, to this depth.
_MAX_QUOTE_DEPTH = 32
# The words after each program word or verb that starts a match in the
# reading of quoted text (see ``_quoted_hit``).
_WORD_BUDGET = 100_000
# Characters of the paths worked out (each path written, with the working
# directory it is read against). A path already worked out costs nothing.
_PATH_BUDGET = 1_000_000
# Characters the cache of worked-out paths may keep.
_SEEN_LIMIT = 1_000_000

_TOO_DEEP = "command nested too deeply to inspect"
_TOO_LONG = "command too long to inspect"


@dataclass(slots=True)
class _Work:
    """The work one recognition has left. One is made for each ``recognize`` call.

    Every reading of the call's text, nested and quoted text included,
    spends from the same budgets, so the total stays linear in its length.
    """

    words: int = _WORD_BUDGET
    path_chars: int = _PATH_BUDGET
    # Characters held by the cache of worked-out paths.
    retained: int = 0

    def spend_words(self, count: int) -> bool:
        """Spend ``count`` words. False once the budget is gone."""
        self.words -= count
        return self.words >= 0

    def spend_path(self, count: int) -> bool:
        """Spend ``count`` path characters. False once the budget is gone."""
        self.path_chars -= count
        return self.path_chars >= 0

    @property
    def spent(self) -> bool:
        return self.words < 0 or self.path_chars < 0
