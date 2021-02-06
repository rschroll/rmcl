# Copyright 2021 Robert Schroll
# This file is part of rmcl and is distributed under the MIT license.

import functools
import inspect
import trio

SUFFIX = '_s'

def add_sync(afunc):
    @functools.wraps(afunc, assigned=('__doc__', '__annotations__'))
    def sfunc(*args, **kw):
        async def runner():
            return await afunc(*args, **kw)
        return trio.run(runner)
    sfunc.__name__ = afunc.__name__ + SUFFIX
    sfunc.__qualname__ = afunc.__qualname__ + SUFFIX

    inspect.currentframe().f_back.f_locals[sfunc.__name__] = sfunc
    return afunc
