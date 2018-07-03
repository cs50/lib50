import sys
import time
import requests
from threading import Thread

class Error(Exception):
    pass

class ProgressBar:
    """Show a progress bar starting with message"""
    def __init__(self, message):
        self._message = message
        self._progressing = True
        self._paused = False
        self._thread = None

    def pause(self):
        """Pause the progress bar"""
        self._paused = True

    def unpause(self):
        """Unpause the progress bar"""
        self._paused = False

    def __enter__(self):
        def progress_runner():
            sys.stdout.write(self._message + "...")
            sys.stdout.flush()
            while self._progressing:
                if not self._paused:
                    sys.stdout.write(".")
                    sys.stdout.flush()
                time.sleep(0.5)
            print()

        self._thread = Thread(target=progress_runner)
        self._thread.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._progressing = False
        self._thread.join()

def check_announcements():
    """Check for any announcements from cs50.me, raise Error if so"""
    res = requests.get("https://cs50.me/status/submit50") # TODO change this to submit50.io!
    if res.status_code == 200 and res.text.strip():
        raise Error(res.text.strip())

def push(org, branch, sentinel = None):
    # TODO check announcements
    # TODO check for git 2.7

    with ProgressBar("Connecting"):
        # TODO TODO move, decide on commit name
        # TODO check version vs submit50.io (or cs50.me)
        if sentinel:
            # TODO ensure sentinel exists at org/repo/branch
            pass
        # TODO ensure .push50.yaml exists at org/repo/branch
        # TODO parse .push50.yaml
        # TODO check for missing files
        pass

    with ProgressBar("Authenticating"):
        # TODO authenticate
        pass

    with ProgressBar("Preparing"):
        # TODO clone bare
            # TODO check for any permission errors: CS50.me / wrong username
        # TODO .gitattribute stuff
        # TODO git config
        # TODO add files to staging area
        # TODO git lfs
        # TODO check that at least 1 file is staged
        pass

    # TODO Submit50 special casing was here (academic honesty)

    with ProgressBar("Uploading"):
        # TODO commit + push
        pass

# example check50 call
push("check50", "hello", sentinel = ".check50.yaml")

"""
with ProgressBar("Connecting") as progress_bar:
    time.sleep(5)
    progress_bar.pause()
    time.sleep(5)
    progress_bar.unpause()
    time.sleep(5)
"""
