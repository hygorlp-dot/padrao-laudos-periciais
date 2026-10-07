from __future__ import annotations

from threading import Thread


def live_request_workers(server) -> tuple[Thread, ...]:
    """Request worker threads of a ThreadingMixIn server that are still alive.

    ThreadingMixIn exposes a non-iterable class-level `_NoThreads` placeholder
    as `_threads` until `process_request` installs the instance-level list on
    the first accepted connection (#300). Only that instance attribute is
    trusted: its absence means no request was accepted yet, while any other
    non-iterable value still raises instead of being read as "no workers".
    Callers must call this on every poll; a reference taken earlier may be the
    placeholder that the first request replaces.
    """
    threads = vars(server).get("_threads")
    if threads is None:
        return ()
    return tuple(thread for thread in threads if thread.is_alive())
