# Copyright 2020-2021 Robert Schroll
# This file is part of rmcl and is distributed under the MIT license.

import datetime

def now():
    return datetime.datetime.now(datetime.timezone.utc)
