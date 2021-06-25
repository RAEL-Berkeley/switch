"""
Tool to generate graphs for a scenario.

Run "switch graph -h" for details.
"""

import os, argparse

from switch_model.utilities import query_yes_no
from switch_model.tools.graphing.main import Scenario, graph_scenarios


def main(args=None):
    # Create the command line interface
    parser = argparse.ArgumentParser(description="Create graphs for a single set of SWITCH results.")
    parser.add_argument("--graph-dir", type=str,
                        help="Name of the folder where the graphs should be saved")
    parser.add_argument("--overwrite", default=False, action="store_true",
                        help="Don't prompt before overwriting the existing folder")
    args = parser.parse_args(args)

    # Create the graphs (with a single scenario)
    graph_scenarios(scenarios=[Scenario()], graph_dir=args.graph_dir, overwrite=args.overwrite)
