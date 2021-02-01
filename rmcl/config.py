# Copyright 2021 Robert Schroll
# This file is part of rmcl and is distributed under the MIT license.

import json
from xdg import xdg_config_home

CONFIG_FILE = xdg_config_home() / 'rmcl' / 'config.json'


class Config(dict):

    def __init__(self):
        super().__init__()
        if CONFIG_FILE.exists():
            super().update(json.load(CONFIG_FILE.open('r')))
        else:
            CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)

    def _save(self):
        json.dump(self, CONFIG_FILE.open('w'), indent=2)

    def __setitem__(self, key, value):
        super().__setitem__(key, value)
        self._save()

    def update(self, other):
        super().update(other)
        self._save()

    def __delitem__(self, key):
        super().__delitem__(key)
        self._save()
