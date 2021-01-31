# Copyright 2019 Stijn Van Campenhout
# Copyright 2021 Robert Schroll
# This file is part of rmcl and is distributed under the MIT license.

from pathlib import Path
from yaml import BaseLoader
from yaml import load as yml_load
from yaml import dump as yml_dump
from typing import Dict
from xdg import xdg_config_home

CONFIG_FILE = xdg_config_home() / 'rmcl' / 'config.yaml'


def load() -> dict:
    """Load the config file"""

    config: Dict[str, str] = {}
    if CONFIG_FILE.exists():
        with CONFIG_FILE.open('r') as config_file:
            config = dict(yml_load(config_file.read(), Loader=BaseLoader))

    return config


def dump(config: dict) -> None:
    """Dump config to the config file

    Args:
        config: A dict containing data to dump to the
            config file.
    """

    with CONFIG_FILE.open('w') as config_file:
        config_file.write(yml_dump(config))
