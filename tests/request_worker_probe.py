from __future__ import annotations

from threading import Thread


def live_request_workers(server) -> tuple[Thread, ...]:
    """Request worker threads of a ThreadingMixIn server that are still alive.

    ThreadingMixIn exposes a non-iterable class-level `_NoThreads` placeholder
    as `_threads` until `process_request` installs the instance-level list on
    the first accepted connection (#300). Only that instance attribute is
    trusted: its absence means no request was accepted yet, while any other
    value (including None) is iterated and raises if it is not iterable,
    instead of being read as "no workers". Callers must call this on every
    poll; a reference taken earlier may be the placeholder that the first
    request replaces.

    Only servers whose list actually records workers (`block_on_close` true,
    `daemon_threads` false) are accepted. After `server_close` the stdlib
    empties the list while joining, so an empty result there is guaranteed by
    that join, not by this probe.
    """
    if not server.block_on_close or server.daemon_threads:
        raise ValueError("server does not record its request workers")
    if "_threads" not in vars(server):
        return ()
    return tuple(thread for thread in vars(server)["_threads"] if thread.is_alive())
