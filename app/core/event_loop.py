import asyncio
import selectors
import sys


def loop_factory() -> asyncio.AbstractEventLoop:
    """psycopg async connections require a selector-based loop on Windows."""
    if sys.platform == "win32":
        return asyncio.SelectorEventLoop(selectors.SelectSelector())
    return asyncio.new_event_loop()
