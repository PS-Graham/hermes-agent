"""Michael's Hermes customizations, packaged as a plugin so `hermes update` leaves them alone."""

from __future__ import annotations

import logging
import os

from . import live_sessions, pre_compaction_review

logger = logging.getLogger(__name__)

_DISABLE_MANAGED_NOUS_ENV = "HERMES_DISABLE_MANAGED_NOUS_TOOLS"


def _managed_nous_tools_disabled(*, force_fresh: bool = False) -> bool:
    return False


def _apply_managed_nous_switch() -> bool:
    """Force ``managed_nous_tools_enabled`` off when the env switch is truthy.

    Swaps the function's code rather than its module attribute: a dozen modules bind the name
    with ``from tools.tool_backend_helpers import ...``, and those bindings would keep the
    original. Skips the import entirely when the switch is unset.
    """
    from utils import is_truthy_value

    if not is_truthy_value(os.getenv(_DISABLE_MANAGED_NOUS_ENV), default=False):
        return False
    from tools import tool_backend_helpers

    tool_backend_helpers.managed_nous_tools_enabled.__code__ = _managed_nous_tools_disabled.__code__
    return True


def register(ctx) -> None:
    ctx.register_cli_command(
        "live",
        help="Inspect and control tmux-managed live Hermes sessions",
        setup_fn=live_sessions.configure_parser,
        handler_fn=live_sessions.dispatch,
        description="Inspect and control tmux-managed live Hermes sessions",
    )
    try:
        _apply_managed_nous_switch()
    except Exception:
        logger.warning("Could not apply %s", _DISABLE_MANAGED_NOUS_ENV, exc_info=True)

    # Hooked only when enabled: a pre_api_request subscriber makes Hermes build the full
    # hook payload on every API call.
    settings = pre_compaction_review.load_settings()
    if settings.enabled:
        review = pre_compaction_review.PreCompactionReview(settings)
        ctx.register_hook("pre_api_request", review.on_pre_api_request)
        ctx.register_hook("pre_auxiliary_call", review.on_pre_auxiliary_call)
