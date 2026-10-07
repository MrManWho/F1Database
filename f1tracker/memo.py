"""4.0.0-beta.13: remember what a page works out from a league while that page is being built.

One page used to work out the same standings many times over (the Home page did it 27 times: the top bar, the
timing tower, the press questions for each driver, the round gate...). Results worked out from a league connection
are now kept on that connection and reused, but only while nothing has been written through it: SQLite counts
every row changed on a connection (total_changes), and any change empties the store. A connection lives for one
request, so nothing is kept between requests, between leagues or between people, and nothing can be shown stale.
Callers get their own copy, so changing what they were given never changes what's kept.
"""

import copy
from functools import wraps


def per_connection(fn=None, *, copier=copy.deepcopy):
    """Decorator for fn(conn, ...). copier makes each caller's copy (dict for a flat {key: number} result)."""
    if fn is None:
        return lambda f: per_connection(f, copier=copier)

    @wraps(fn)
    def wrapper(conn, *args, **kwargs):
        store = getattr(conn, "memo", None)
        if store is None:                     # not a league connection (or a plain sqlite3 one in a script)
            return fn(conn, *args, **kwargs)
        changes = conn.total_changes
        if conn.memo_changes != changes:
            store.clear()
            conn.memo_changes = changes
        try:
            key = (fn.__module__, fn.__qualname__, args, tuple(sorted(kwargs.items())))
            hit = store.get(key, _MISS)
        except TypeError:                     # an argument that can't be a key (a list, a dict): just work it out
            return fn(conn, *args, **kwargs)
        if hit is _MISS:
            hit = fn(conn, *args, **kwargs)
            if conn.total_changes == changes:   # it didn't write anything itself while working it out
                store[key] = hit
            else:
                return hit
        return copier(hit)
    wrapper.uncached = fn
    return wrapper


_MISS = object()


def rows_copy(rows):
    """A caller's own copy of a list of row dicts: each row, and each dict or list inside it, is new."""
    return [{k: (v.copy() if isinstance(v, (dict, list)) else v) for k, v in r.items()} for r in rows]
