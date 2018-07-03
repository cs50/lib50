import sys
import time
import contextlib
import requests
from threading import Thread

class Error(Exception):
    pass

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
        print()

    try:
        progressing = True
        thread = Thread(target=progress_runner)
        thread.start()
        yield
    finally:
        progressing = False
        thread.join()

def check_announcements():
    """Check for any announcements from cs50.me, raise Error if so"""
    res = requests.get("https://cs50.me/status/submit50") # TODO change this to submit50.io!
    if res.status_code == 200 and res.text.strip():
        raise Error(res.text.strip())

def push(org, branch, sentinel = None):
    # TODO check announcements
    # TODO check for git 2.7

    with progress("Connecting"):
        # TODO TODO move, decide on commit name
        # TODO check version vs submit50.io (or cs50.me)
        if sentinel:
            # TODO ensure sentinel exists at org/repo/branch
            pass
        # TODO ensure .push50.yaml exists at org/repo/branch
        # TODO parse .push50.yaml
        # TODO check for missing files
        pass

    with progress("Authenticating"):
        # TODO authenticate
        pass

    with progress("Preparing"):
        # TODO clone bare
            # TODO check for any permission errors: CS50.me / wrong username
        # TODO .gitattribute stuff
        # TODO git config
        # TODO add files to staging area
        # TODO git lfs
        # TODO check that at least 1 file is staged
        pass

    # TODO Submit50 special casing was here (academic honesty)

    with progress("Uploading"):
        # TODO commit + push
        pass

# example check50 call
push("check50", "hello", sentinel = ".check50.yaml")
