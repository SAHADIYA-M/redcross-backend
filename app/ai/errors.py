class AIError(Exception):
    """Base class for AI-related errors."""


class AIConfigurationError(AIError):
    """Raised when the AI service is not configured (e.g. missing API key)."""


class AIGatewayError(AIError):
    """Raised when the upstream AI service fails (network, timeout, API)."""


class AIResponseError(AIError):
    """Raised when the AI response is empty, malformed, or fails validation."""