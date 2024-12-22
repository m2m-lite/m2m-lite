"""Configuration loader for m2m-lite."""

import os
import sys

import yaml
from yaml.loader import SafeLoader


def get_app_path():
    """
    Get the base directory of the application.

    Handles running from source or as an executable.
    """
    if getattr(sys, "frozen", False):
        # Running in a bundle (PyInstaller)
        return os.path.dirname(sys.executable)
    else:
        # Running in a normal Python environment
        return os.path.dirname(os.path.abspath(__file__))

# Initialize an empty dictionary to store the configuration
relay_config = {}

# Determine the path to the config.yaml file
config_path = os.path.join(get_app_path(), "config.yaml")

# Check if the config.yaml file exists
if not os.path.isfile(config_path):
    print(f"Configuration file not found: {config_path}")
else:
    # Load the configuration from the YAML file
    with open(config_path, "r") as f:
        relay_config = yaml.load(f, Loader=SafeLoader)
