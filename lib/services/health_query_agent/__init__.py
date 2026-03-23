"""
Health Query Agent package.
"""

__all__ = ["HealthQueryAgentService"]


def __getattr__(name: str):
    if name == "HealthQueryAgentService":
        from .service import HealthQueryAgentService

        return HealthQueryAgentService
    raise AttributeError(name)
