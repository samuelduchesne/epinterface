"""Configuration settings for epinterface, loaded from environment variables."""

from typing import Any

from idfkit import EnergyPlusNotFoundError, version_string
from idfkit.simulation import find_energyplus
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _normalize_energyplus_version(value: str) -> str:
    """Normalize EnergyPlus version string to X.Y.Z format.

    Accepts formats like "22.2.0", "22.2", "22-2-0", "22-2".
    """
    # Replace hyphens with dots for formats like "22-2-0"
    normalized = value.strip().replace("-", ".")
    # Ensure we have at least X.Y format
    parts = normalized.split(".")
    if len(parts) == 2:
        return f"{parts[0]}.{parts[1]}.0"
    return ".".join(parts[:3])  # Take at most major.minor.patch


class EnergyPlusVersionNotSetError(ValueError):
    """Raised when an EnergyPlus version is required but none is configured."""


def _get_installed_energyplus_version() -> str | None:
    """Get the version of the discovered EnergyPlus installation as X.Y.Z."""
    try:
        return version_string(find_energyplus().version)
    except EnergyPlusNotFoundError:
        return None


class EnergyPlusSettings(BaseSettings):
    """Settings for EnergyPlus version and configuration.

    The EnergyPlus version is used when creating IDF objects via idfkit.
    It determines which EnergyPlus schema/IDD version is used for parsing and validation.
    """

    model_config = SettingsConfigDict(
        env_prefix="EPINTERFACE_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    energyplus_version: str | None = Field(
        default_factory=_get_installed_energyplus_version
    )

    @property
    def version_tuple(self) -> tuple[int, int, int]:
        """Get the configured EnergyPlus version as (major, minor, patch)."""
        if self.energyplus_version:
            major, minor, patch = (int(p) for p in self.energyplus_version.split("."))
            return (major, minor, patch)
        msg = "No EnergyPlus version specified."
        raise EnergyPlusVersionNotSetError(msg)

    @field_validator("energyplus_version", mode="before")
    @classmethod
    def normalize_version(cls, v: Any) -> str | None:
        """Normalize version string from env (e.g. 22-2-0 -> 22.2.0)."""
        if v is None:
            return None
        if not isinstance(v, str) or not v.strip():
            return None
        return _normalize_energyplus_version(v)


# Singleton instance for application-wide use
energyplus_settings = EnergyPlusSettings()
