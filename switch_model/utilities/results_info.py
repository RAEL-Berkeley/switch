import pandas as pd
from tabulate import tabulate

_general_info_data = []
_scenario_info_data = pd.DataFrame()

def add_general_info(name, val):
    _general_info_data.append((name, val))

def add_results_info(name: str, scenario, value=""):
    _scenario_info_data.loc[name, scenario] = value

def save_info(filepath):
    with open(filepath, "w") as f:
        f.write(f"##########\n"
                f" GENERAL\n"
                f"##########\n\n")
        f.write("\n".join(map(lambda v: str(v[0]) + ": " + str(v[1]), _general_info_data)) + "\n\n")

        f.write(f"##########\n"
                f" RESULTS\n"
                f"##########\n\n")

        f.write(
            tabulate(pd.DataFrame(_scenario_info_data),
                     headers=_scenario_info_data.columns)
        )