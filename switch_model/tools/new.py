"""
Script that prepares a folder to be used by switch.

This script:
- Creates a template config.yaml file in the repository.
"""
import shutil
import os
import argparse


def copy_template_to_workdir(template_name):
    shutil.copyfile(
        os.path.join(os.path.dirname(__file__), f"templates/{template_name}"),
        os.path.join(os.getcwd(), template_name)
    )


def create_run_config():
    copy_template_to_workdir("config.yaml")
    print("IMPORTANT: Edit config.yaml to specify your options.")


def create_sampling_config():
    copy_template_to_workdir("sampling.yaml")
    print("IMPORTANT: Edit sampling.yaml to specify your options.")


def main():
    parser = argparse.ArgumentParser(description="Tool to setup your folder for either a new run or a new sampling config.")
    parser.add_argument(
        "type",
        choices=["run", "sampling_config"],
        help="Pick between setting up a new run or a sampling strategy."
    )
    args = parser.parse_args()
    if args.type == "run":
        create_run_config()
    elif args.type == "sampling_config":
        create_sampling_config()