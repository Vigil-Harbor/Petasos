"""Host-agnostic enforcement policy.

Decisions, the cold-start gate, approval excerpts, the model-facing text, and
the signed event spool. A host turns a decision into its own hook result.
"""

from petasos.enforce.events import (
    SPOOL_CAP_BYTES,
    classify_integrity_failure,
    drain_enforcement_events,
    emit_console_event,
    emit_enforcement_event,
    install_spool_resolver,
    rotate_spool,
    set_spool_key,
    spool_size,
    verify_event,
)
from petasos.enforce.messages import (
    format_block_message,
    format_content_block,
    format_pipeline_block_message,
    format_result_notice,
    shorten_rule_id,
)

__all__ = [
    "SPOOL_CAP_BYTES",
    "classify_integrity_failure",
    "drain_enforcement_events",
    "emit_console_event",
    "emit_enforcement_event",
    "format_block_message",
    "format_content_block",
    "format_pipeline_block_message",
    "format_result_notice",
    "install_spool_resolver",
    "rotate_spool",
    "set_spool_key",
    "shorten_rule_id",
    "spool_size",
    "verify_event",
]
