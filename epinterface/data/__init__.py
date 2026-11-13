"""This module provides the path to the EnergyPlus artifacts directory."""

from pathlib import Path

EnergyPlusArtifactDir = Path(__file__).parent

DefaultEPWPath = next(EnergyPlusArtifactDir.glob("*.epw"))
DefaultDDYPath = next(EnergyPlusArtifactDir.glob("*.ddy"))
DefaultEPWZipPath = next(EnergyPlusArtifactDir.glob("*.zip"))

__all__ = [
    "DefaultDDYPath",
    "DefaultEPWPath",
    "DefaultEPWZipPath",
    "EnergyPlusArtifactDir",
]
