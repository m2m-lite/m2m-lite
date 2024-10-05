import yaml
from yaml.loader import SafeLoader

# Load configuration
with open("config.yaml", "r") as f:
    relay_config = yaml.load(f, Loader=SafeLoader)
