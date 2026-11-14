"""Tests for adding envelope components to an IDF document."""

import pytest

from epinterface.document import EPDocument
from epinterface.interface import InfDesignFlowRateCalculationMethodType
from epinterface.sbem.components.envelope import InfiltrationComponent


@pytest.mark.parametrize(
    "is_on,rates,calculation_method_main,calculation_method_attic",
    [
        (True, (0.5, 0.0002), "Flow/ExteriorArea", "AirChanges/Hour"),
        (False, (0.25, 0.0001), "AirChanges/Hour", "Flow/ExteriorArea"),
    ],
)
def test_infiltration_comp(
    doc: EPDocument,
    is_on: bool,
    rates: tuple[float, float],
    calculation_method_main: InfDesignFlowRateCalculationMethodType,
    calculation_method_attic: InfDesignFlowRateCalculationMethodType,
):
    """Test the infiltration component."""
    inf_name = "Test_Infiltration"
    attic_inf_name = f"{inf_name}_Attic"
    main_zone_name = "Test_Zone"
    attic_zone_name = "Test_Zone_Attic"
    main_ach, main_flow_rate = rates
    attic_ach, attic_flow_rate = main_ach * 2, main_flow_rate * 2
    expected_main_inf_name = f"{main_zone_name}_{inf_name}_INFILTRATION"
    expected_attic_inf_name = f"{attic_zone_name}_{attic_inf_name}_INFILTRATION"
    infiltration = InfiltrationComponent(
        Name=inf_name,
        AirChangesPerHour=main_ach,
        FlowPerExteriorSurfaceArea=main_flow_rate,
        CalculationMethod=calculation_method_main,
        IsOn=is_on,
        ConstantCoefficient=0.606,
        TemperatureCoefficient=3.6359996e-2,
        WindVelocityCoefficient=0.117765,
        WindVelocitySquaredCoefficient=0,
        AFNAirMassFlowCoefficientCrack=0,
    )
    assert expected_main_inf_name not in doc["ZoneInfiltration:DesignFlowRate"]
    assert expected_attic_inf_name not in doc["ZoneInfiltration:DesignFlowRate"]
    attic_infiltration = infiltration.model_copy(
        deep=True,
        update={
            "Name": attic_inf_name,
            "AirChangesPerHour": attic_ach,
            "FlowPerExteriorSurfaceArea": attic_flow_rate,
            "CalculationMethod": calculation_method_attic,
        },
    )
    doc = infiltration.add_infiltration_to_idf_zone(doc, main_zone_name)
    doc = attic_infiltration.add_infiltration_to_idf_zone(doc, attic_zone_name)

    main_inf = doc["ZoneInfiltration:DesignFlowRate"].get(expected_main_inf_name)
    attic_inf = doc["ZoneInfiltration:DesignFlowRate"].get(expected_attic_inf_name)
    if is_on:
        assert main_inf is not None
        assert main_inf.air_changes_per_hour == main_ach
        assert main_inf.flow_rate_per_exterior_surface_area == main_flow_rate
        assert main_inf.design_flow_rate_calculation_method == calculation_method_main
        assert attic_inf is not None
        assert attic_inf.flow_rate_per_exterior_surface_area == attic_flow_rate
        assert attic_inf.air_changes_per_hour == attic_ach
        assert attic_inf.design_flow_rate_calculation_method == calculation_method_attic
    else:
        assert main_inf is None
        assert attic_inf is None
