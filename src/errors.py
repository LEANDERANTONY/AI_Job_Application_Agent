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


class AuthRequiredError(AppError):
    """Raised when an authenticated context is required but the request
    arrives without one (missing tokens) or its tokens are expired /
    invalid.

    Routes translate this to HTTP 401. Keeping it distinct from
    InputValidationError lets the frontend distinguish "your session
    expired, please re-auth" from "your payload was malformed" — they
    have very different user remediations. Previously both paths were
    collapsed into InputValidationError and surfaced as 400, which
    blocked the frontend's re-auth flow from triggering."""


class AgentExecutionError(AppError):
    """A *content* failure in an LLM-backed step.

    Raised when the model responded but the response is unusable for a
    reason retrying-bigger won't fix: malformed JSON on a *complete*
    response, schema drift, or required fields still missing after the
    output budget escalated all the way to the ceiling. Callers treat
    this as "this particular step degraded" and fall back per-step.

    NOT for provider availability problems — see
    ``OpenAIUnavailableError`` for that.
    """


class OpenAIUnavailableError(AgentExecutionError):
    """A *transport / availability* failure talking to OpenAI.

    Network error, timeout, 5xx, rate-limit after the SDK already
    backed off, auth/quota rejection — i.e. we never got a usable
    response at all. Distinct from a content failure because the
    remediation is completely different: there's nothing wrong with
    the request, the provider is just down, so retrying individual
    agents is pointless. The orchestrator short-circuits the whole
    run to deterministic output and surfaces an honest "our AI
    provider is having a moment" notice to the user instead of
    silently shipping a degraded result.

    Subclasses ``AgentExecutionError`` so every existing
    ``except AgentExecutionError`` site keeps catching it unchanged;
    only the code that wants to distinguish an outage (the
    orchestrator) needs the ``isinstance`` check.
    """


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
