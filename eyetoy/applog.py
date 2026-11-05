"""File logging, the only diagnostic channel of a windowed build.

A --windowed executable has no console: without this, any exception raised in
a Tk callback or a worker thread would vanish without a trace.
"""

from __future__ import annotations

import logging
import sys
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path

from . import paths

log = logging.getLogger("eyetoy")


def setup() -> Path | None:
    """Log to %LOCALAPPDATA%\\EyeToyStudio\\eyetoy.log. Returns the file path."""
    path = paths.data_dir() / "eyetoy.log"
    handlers: list[logging.Handler] = []
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(RotatingFileHandler(path, maxBytes=512 * 1024,
                                            backupCount=2, encoding="utf-8"))
    except OSError:
        path = None
    if sys.stderr is not None:              # None in a windowed build
        handlers.append(logging.StreamHandler())
    logging.basicConfig(
        level=logging.INFO, handlers=handlers, force=True,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")

    def excepthook(kind, value, tb) -> None:
        log.critical("unhandled exception", exc_info=(kind, value, tb))

    def thread_excepthook(args: threading.ExceptHookArgs) -> None:
        if args.exc_type is SystemExit:
            return
        log.critical("exception in thread %s",
                     args.thread.name if args.thread else "?",
                     exc_info=(args.exc_type, args.exc_value,
                               args.exc_traceback))

    sys.excepthook = excepthook
    threading.excepthook = thread_excepthook
    return path
