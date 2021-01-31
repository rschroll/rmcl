# Copyright 2020-2021 Robert Schroll
# This file is part of rmcl and is distributed under the MIT license.

import datetime
import re

def now():
    return datetime.datetime.now(datetime.timezone.utc)

def parse_datetime(dt):
    # fromisoformat needs 0, 3, or 6 decimal places for the second, but
    # we can get other numbers from the API.  Since we're not doing anything
    # that time-sensitive, we'll just chop off the fractional seconds.
    dt = re.sub(r'\.\d*', '', dt).replace('Z', '+00:00')
    return datetime.datetime.fromisoformat(dt)
