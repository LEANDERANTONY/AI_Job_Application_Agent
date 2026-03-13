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
