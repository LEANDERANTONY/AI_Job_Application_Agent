class AppError(Exception):
    """Base application error with a user-facing message."""

    def __init__(self, user_message, *, details=None):
        super().__init__(user_message)
        self.user_message = user_message
        self.details = details


class ParsingError(AppError):
    """Raised when an uploaded or sample file cannot be parsed safely."""


class InputValidationError(AppError):
    """Raised when a user input or UI state is invalid for the current action."""


class AgentExecutionError(AppError):
    """Reserved for future supervised-agent execution failures."""


class ExportError(AppError):
    """Raised when a report export cannot be generated safely."""


class BackendIntegrationError(AppError):
    """Raised when a backend-owned service request fails or returns invalid data."""


class QuotaExceededError(AppError):
    """Raised when a tier quota gate would be breached by the requested action.

    Carries the structured fields the FastAPI handler needs to assemble the
    canonical 429 payload: counter name, current count, cap, period key, and
    the resolved tier. Call sites raise this from `backend.quota` after the
    atomic Supabase RPC reports a `P0001` quota_exceeded condition; the
    backend's global exception handler maps the instance to a JSON response.

    Stored fields:
        counter:      The counter_name passed to check_and_increment
                      (e.g. "tailored_applications"). The frontend uses this
                      to decide which upgrade nudge copy to render.
        current:      The user's current count for the period before the
                      failed increment. Useful for the toast ("3 of 3 used").
        cap:          The tier's cap for this counter (post-resolve_user_tier).
                      Always a non-negative int -- UNLIMITED counters never
                      raise this error.
        reset_period: The period_key the counter rolls over on
                      ("YYYY-MM" for monthly, "lifetime" for lifetime, etc.).
                      The frontend renders "resets on the 1st" only for
                      monthly counters; lifetime/persistent counters get a
                      different message.
        tier:         The tier returned by resolve_user_tier at the time of
                      rejection -- carried so the response payload doesn't
                      need to call the resolver again in the handler.
    """

    def __init__(
        self,
        user_message,
        *,
        counter,
        current,
        cap,
        reset_period,
        tier,
        details=None,
    ):
        super().__init__(user_message, details=details)
        self.counter = counter
        self.current = current
        self.cap = cap
        self.reset_period = reset_period
        self.tier = tier
