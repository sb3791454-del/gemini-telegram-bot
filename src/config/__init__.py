"""Configuration package for Sultan Assistant."""

from config.settings import Settings, DEFAULT_GEMINI_MODEL
from config.prompts import (
    WELCOME_TEXT,
    HELP_TEXT,
    RESET_TEXT,
    UNAUTHORIZED_DENIAL_TEXT,
    FALLBACK_ERROR_TEXT,
    IMAGE_ERROR_TEXT,
    DEFAULT_VISION_PROMPT,
)

__all__ = [
    "Settings",
    "DEFAULT_GEMINI_MODEL",
    "WELCOME_TEXT",
    "HELP_TEXT",
    "RESET_TEXT",
    "UNAUTHORIZED_DENIAL_TEXT",
    "FALLBACK_ERROR_TEXT",
    "IMAGE_ERROR_TEXT",
    "DEFAULT_VISION_PROMPT",
]
