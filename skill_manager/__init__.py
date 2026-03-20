"""
Skill Manager — Enterprise skill lifecycle manager for AI agents.

Gate-and-govern model: every skill is vetted before deployment and
governed at runtime via signature verification and permission enforcement.
"""

__version__ = "0.1.0"
__author__ = "Enterprise AI Security Team"

__all__ = [
    "SkillManager",
]


def __getattr__(name: str):
    if name == "SkillManager":
        from .core.manager import SkillManager

        return SkillManager
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
