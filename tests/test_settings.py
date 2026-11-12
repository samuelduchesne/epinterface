"""Tests for EnergyPlus settings resolution."""

import pytest

from epinterface.settings import EnergyPlusSettings, EnergyPlusVersionNotSetError


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
