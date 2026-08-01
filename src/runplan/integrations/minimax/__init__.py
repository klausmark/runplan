"""MiniMax plan generation adapter."""

from .client import (
    MiniMaxAuthenticationError,
    MiniMaxClient,
    MiniMaxError,
    MiniMaxProtocolError,
    MiniMaxRateLimitError,
    MiniMaxTimeoutError,
    MiniMaxUnconfiguredError,
    MiniMaxUpstreamError,
)

__all__ = [
    "MiniMaxAuthenticationError",
    "MiniMaxClient",
    "MiniMaxError",
    "MiniMaxProtocolError",
    "MiniMaxRateLimitError",
    "MiniMaxTimeoutError",
    "MiniMaxUnconfiguredError",
    "MiniMaxUpstreamError",
]
