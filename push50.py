import sys
import time
import contextlib
from threading import Thread

@contextlib.contextmanager
def progress(message):
    """Show a progress bar starting with message"""
    def progress_runner():
        sys.stdout.write(message + "...")
        sys.stdout.flush()
        while progressing:
            sys.stdout.write(".")
            sys.stdout.flush()
            time.sleep(0.5)

    try:
        progressing = True
        thread = Thread(target=progress_runner)
        thread.start()
        yield
    finally:
        progressing = False
        thread.join()

with progress("connecting"):
    time.sleep(5)
