"""Tests for EnergyPlus settings resolution."""

import re

import pytest
from idfkit import EnergyPlusNotFoundError

from epinterface import settings as settings_module
from epinterface.analysis.energy_and_peak import (
    DESIRED_METERS_FOR_VERSION,
    TABULAR_DATA_COLUMNS_FOR_VERSION,
)
from epinterface.settings import (
    SUPPORTED_ENERGYPLUS_MAJORS,
    EnergyPlusSettings,
    EnergyPlusVersionNotSetError,
    UnsupportedEnergyPlusVersionError,
)


def test_version_tuple_from_env(monkeypatch: pytest.MonkeyPatch):
    """The env var is normalised and parsed into a version tuple."""
    monkeypatch.setenv("EPINTERFACE_ENERGYPLUS_VERSION", "24-2")
    assert EnergyPlusSettings().version_tuple == (24, 2, 0)


def test_version_tuple_unset_raises():
    """An unset version raises a dedicated error."""
    with pytest.raises(EnergyPlusVersionNotSetError):
        _ = EnergyPlusSettings(energyplus_version=None).version_tuple


def test_default_uses_installed_energyplus(monkeypatch: pytest.MonkeyPatch):
    """Without an env var the installed EnergyPlus is used."""
    monkeypatch.delenv("EPINTERFACE_ENERGYPLUS_VERSION", raising=False)
    assert EnergyPlusSettings().energyplus_version is not None


def test_default_is_supported_version(monkeypatch: pytest.MonkeyPatch):
    """The default is an installed version of a supported major, as X.Y.Z."""
    monkeypatch.delenv("EPINTERFACE_ENERGYPLUS_VERSION", raising=False)
    version = EnergyPlusSettings().energyplus_version
    assert version is not None
    assert re.fullmatch(r"\d+\.\d+\.\d+", version)
    assert int(version.split(".")[0]) in SUPPORTED_ENERGYPLUS_MAJORS


def test_default_none_when_nothing_installed(monkeypatch: pytest.MonkeyPatch):
    """No installation found for any supported major gives a None default."""

    def _raise(**_kwargs: object):
        raise EnergyPlusNotFoundError([])

    monkeypatch.delenv("EPINTERFACE_ENERGYPLUS_VERSION", raising=False)
    monkeypatch.setattr(settings_module, "find_energyplus", _raise)
    assert EnergyPlusSettings().energyplus_version is None


def test_unsupported_major_raises(monkeypatch: pytest.MonkeyPatch):
    """A version whose major has no per-major tables raises a clear error."""
    monkeypatch.setenv("EPINTERFACE_ENERGYPLUS_VERSION", "26.1.0")
    with pytest.raises(UnsupportedEnergyPlusVersionError, match=r"26\.1\.0"):
        _ = DESIRED_METERS_FOR_VERSION[EnergyPlusSettings().supported_major]


def test_supported_majors_match_tables():
    """The supported-major constant stays in sync with the per-major tables."""
    assert set(SUPPORTED_ENERGYPLUS_MAJORS) == set(DESIRED_METERS_FOR_VERSION)
    assert set(SUPPORTED_ENERGYPLUS_MAJORS) == set(TABULAR_DATA_COLUMNS_FOR_VERSION)
