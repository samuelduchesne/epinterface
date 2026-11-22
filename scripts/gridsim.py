"""Test the ClimateStudio interface."""

import json

import pandas as pd
from idfkit import save_idf

from epinterface.climate_studio.builder import Model, ShoeboxGeometry
from epinterface.climate_studio.interface import ClimateStudioLibraryV2
from epinterface.weather import WeatherUrl


def run():
    """Run the test."""
    yr_brackets = ["pre_1975", "btw_1975_2003", "post_2003"]
    sizes = ["SF", "MF"]
    # conditioned_basement = [(False, False), (True, False), (True, True)]
    basement_config = [(True, False)]
    num_stories = 3
    wwr = 0.15
    f2f = 3.5
    w = 10
    d = 10
    zoning = "by_storey"

    all_results: list[pd.DataFrame] = []
    for size in sizes:
        for yr_bracket in yr_brackets:
            for has_basement, basement_conditioned in basement_config:
                lib_path = "notebooks/everett_lib.json"

                with open(lib_path) as f:
                    lib_data = json.load(f)
                lib = ClimateStudioLibraryV2.model_validate(lib_data)

                for env in lib.Envelopes.values():
                    if env.WindowDefinition is None:
                        msg = f"Envelope {env.Name} has no window definition"
                        raise ValueError(msg)
                    env.WindowDefinition.Construction = f"Template_{yr_bracket}"
                # for su in lib.SpaceUses.values():
                #     su.HotWater.FlowRatePerPerson = 0
                # for window in lib.GlazingConstructions.values():
                #     window.UValue = 5.894
                #     window.SHGF = 0.905
                #     window.TVis = 0.913

                model = Model(
                    Weather=WeatherUrl(  # pyright: ignore [reportCallIssue]
                        "https://climate.onebuilding.org/WMO_Region_4_North_and_Central_America/USA_United_States_of_America/MA_Massachusetts/USA_MA_Boston-Logan.Intl.AP.725090_TMYx.2009-2023.zip"
                    ),
                    geometry=ShoeboxGeometry(
                        x=0,
                        y=0,
                        w=w,
                        d=d,
                        h=f2f,
                        num_stories=num_stories,
                        perim_depth=3,
                        zoning=zoning,
                        roof_height=None,
                        basement=has_basement,
                        wwr=wwr,
                    ),
                    conditioned_basement=basement_conditioned,
                    space_use_name=f"MA_{size}_{yr_bracket}",
                    envelope_name=f"MA_{size}_{yr_bracket}",
                    lib=lib,
                )
                doc, results, _warning_text = model.run()

                df = results.to_frame().T
                df.index = pd.MultiIndex.from_tuples(
                    [
                        (
                            size,
                            yr_bracket,
                            has_basement,
                            basement_conditioned,
                        )
                    ],
                    names=["size", "year", "has_basement", "conditioned_basement"],
                )
                all_results.append(df)
                save_idf(
                    doc,
                    f"notebooks/cache/everett_{size}_{yr_bracket}_HB{has_basement}_BC{basement_conditioned}.idf",
                )

    all_results_df = pd.concat(all_results).round()
    print(all_results_df)


if __name__ == "__main__":
    run()
