"""Short-lived first-fire decisions for repeated hooks on the same host call."""

from __future__ import annotations

import hashlib
import json
import threading
from collections import OrderedDict
from dataclasses import dataclass
from typing import TYPE_CHECKING

from petasos.enforce.decisions import Allow, Approve, Decision
from petasos.normalize import canonicalize_tool_name

if TYPE_CHECKING:
    from petasos.enforce.types import ApprovalNotice, Clock, ToolCall

_MAX_RECORDS = 1024
_LIFETIME_S = 300.0
_Key = tuple[str, str | None, str, str, str, str]


@dataclass
class _Record:
    until: float
    decision: Decision | None
    granted: bool = False
    answered: bool = False
    requested: tuple[str, str] | None = None


class Replays:
    """Bounded call identities, never a session or standing permission.

    The owner holds ``lock`` only for bookkeeping, reserving the first fire
    before evaluating it. Other calls retain their own evaluation deadlines.
    Only a matching fresh human answer promotes a recorded ask to an allow.
    """

    def __init__(self, clock: Clock) -> None:
        self.lock = threading.RLock()
        self._clock = clock
        self._records: OrderedDict[_Key, _Record] = OrderedDict()

    def key(self, call: ToolCall, session: str) -> _Key | None:
        """No complete identity or JSON arguments means no reuse."""
        if not call.turn_id or not call.tool_call_id:
            return None
        try:
            # Reject non-JSON values and non-string mapping keys rather than
            # hashing their lossy string representations.
            def check(value: object) -> None:
                if type(value) is dict:
                    for key, item in value.items():
                        if not isinstance(key, str):
                            raise ValueError("non-string key")
                        check(item)
                elif type(value) is list:
                    for item in value:
                        check(item)
                elif value is not None and type(value) not in (str, int, float, bool):
                    raise ValueError("non-JSON value")

            args = dict(call.args)
            check(args)
            encoded = json.dumps(args, sort_keys=True, separators=(",", ":"), allow_nan=False)
        except (TypeError, ValueError, RecursionError):
            return None
        digest = hashlib.sha256(encoded.encode()).hexdigest()
        return (
            session,
            call.host_session,
            call.turn_id,
            call.tool_call_id,
            canonicalize_tool_name(call.tool),
            digest,
        )

    def _expire(self) -> None:
        now = self._clock.monotonic()
        while self._records:
            if next(iter(self._records.values())).until > now:
                break
            self._records.popitem(last=False)

    def allowed(self, key: _Key | None) -> bool:
        """Only a first allow or an answered first ask permits reuse."""
        self._expire()
        row = self._records.get(key) if key is not None else None
        return row is not None and (isinstance(row.decision, Allow) or row.granted)

    def remember(self, key: _Key | None, decision: Decision) -> None:
        """Keep the first decision; a later answer cannot promote a block."""
        self.finish(key, self.reserve(key), decision)

    def reserve(self, key: _Key | None) -> _Record | None:
        """Claim the first fire without holding the lock through its scan."""
        self._expire()
        if key is None or key in self._records:
            return None
        row = _Record(self._clock.monotonic() + _LIFETIME_S, None)
        self._records[key] = row
        if len(self._records) > _MAX_RECORDS:
            self._records.popitem(last=False)
        return row

    def finish(self, key: _Key | None, reservation: _Record | None, decision: Decision) -> None:
        """Only the reserved first fire can fill its still-live record."""
        self._expire()
        if (
            key is not None
            and reservation is not None
            and self._records.get(key) is reservation
            and reservation.decision is None
        ):
            reservation.decision = decision

    def request(self, notice: ApprovalNotice) -> None:
        """Remember that this recorded ask actually reached a human surface."""
        with self.lock:
            self._expire()
            matches = [
                row for key, row in self._records.items() if self._matches(key, row, notice)
            ]
            # The host notice carries no argument digest. If multiple pending
            # calls share its ids and rule, it cannot prove which was approved.
            for row in matches:
                row.requested = (notice.session_key, notice.surface) if len(matches) == 1 else None

    @staticmethod
    def _matches(key: _Key, row: _Record, notice: ApprovalNotice) -> bool:
        return (
            key[1:4] == (notice.session_id, notice.turn_id, notice.tool_call_id)
            and not row.answered
            and isinstance(row.decision, Approve)
            and notice.pattern_key.removeprefix("plugin_rule:") == row.decision.rule_key
        )

    def answer(self, notice: ApprovalNotice) -> None:
        """Match the issued rule and all host correlation fields, from a person."""
        with self.lock:
            self._expire()
            if (
                not notice.turn_id
                or not notice.tool_call_id
                or notice.decided_by not in {None, "human"}
            ):
                return
            for key, row in self._records.items():
                if self._matches(key, row, notice) and row.requested == (
                    notice.session_key,
                    notice.surface,
                ):
                    row.answered = True
                    row.granted = notice.choice in {"once", "session", "always"}
