"""Opt-in development-only overrides for application-level usage limits."""

import os


def gemini_limit_bypass_enabled() -> bool:
    """Return true only for an explicit local development override.

    Both settings are required so a copied or accidentally exposed bypass
    flag cannot disable budgets in production.
    """
    enabled = os.getenv("JOBSAILOR_DEV_BYPASS_GEMINI_LIMITS", "").strip().lower()
    environment = os.getenv("APP_ENV", "").strip().lower()
    return enabled in {"1", "true", "yes", "on"} and environment == "development"
