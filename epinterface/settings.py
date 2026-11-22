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


# Majors with per-version meter/table definitions in epinterface.analysis,
# newest first.
SUPPORTED_ENERGYPLUS_MAJORS: tuple[int, ...] = (25, 24, 23, 22)


class UnsupportedEnergyPlusVersionError(ValueError):
    """Raised when an EnergyPlus major version has no per-version definitions."""


def require_supported_major(major: int, version: str | None = None) -> int:
    """Return `major` if supported, otherwise raise UnsupportedEnergyPlusVersionError."""
    if major not in SUPPORTED_ENERGYPLUS_MAJORS:
        msg = (
            f"EnergyPlus version {version or major} is not supported; "
            f"supported major versions are {sorted(SUPPORTED_ENERGYPLUS_MAJORS)}."
        )
        raise UnsupportedEnergyPlusVersionError(msg)
    return major


class EnergyPlusVersionNotSetError(ValueError):
    """Raised when an EnergyPlus version is required but none is configured."""


# The oldest release epinterface builds documents for (see
# `epinterface.document.SUPPORTED_DOCUMENT_TYPES`): 22.1 is of a supported major
# but names several fields differently, so `minimal_document` refuses it.
_OLDEST_SUPPORTED_RELEASE = (22, 2)


def _get_installed_energyplus_version() -> str | None:
    """Get the newest installed EnergyPlus version (X.Y.Z) epinterface supports."""
    for major in SUPPORTED_ENERGYPLUS_MAJORS:
        for minor in range(9, -1, -1):
            if (major, minor) < _OLDEST_SUPPORTED_RELEASE:
                continue
            try:
                return version_string(
                    find_energyplus(version=f"{major}.{minor}").version
                )
            except EnergyPlusNotFoundError:
                continue
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

    @property
    def supported_major(self) -> int:
        """Get the configured EnergyPlus major version, checked to be supported."""
        return require_supported_major(self.version_tuple[0], self.energyplus_version)

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
