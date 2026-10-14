from __future__ import annotations

import sys
import threading


PROCESSING_LOCK = threading.Lock()
MUTEX_NAME = "Local\\ScreenshotAligner"


def acquire_single_instance_lock(name: str = MUTEX_NAME):
    """Return a process-lifetime Windows mutex, or None if one already exists."""
    if sys.platform != "win32":
        return object()

    import win32api
    import win32event
    import winerror

    handle = win32event.CreateMutex(None, False, name)
    if win32api.GetLastError() == winerror.ERROR_ALREADY_EXISTS:
        win32api.CloseHandle(handle)
        return None
    return handle


def acquire_processing_lock() -> bool:
    return PROCESSING_LOCK.acquire(blocking=False)


def release_processing_lock() -> None:
    PROCESSING_LOCK.release()
