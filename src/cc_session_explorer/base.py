"""Base model config presets for this package."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class FrozenModel(BaseModel):
    """Immutable, strict domain model — the config preset for this package."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class InputModel(BaseModel):
    """Lenient boundary model — ignores unknown keys from external sources."""

    model_config = ConfigDict(extra="ignore")
