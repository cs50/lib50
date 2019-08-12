import os
from . import _

__all__ = ["Error", "InvalidSlugError", "MissingFilesError", "InvalidConfigError", "MissingToolError", "TimeoutError", "ConnectionError"]

class Error(Exception):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.payload = {}

class InvalidSlugError(Error):
    pass

class MissingFilesError(Error):
    def __init__(self, files):
        cwd = os.getcwd().replace(os.path.expanduser("~"), "~", 1)
        super().__init__("{}\n{}\n{}".format(
            _("You seem to be missing these required files:"),
            "\n".join(files),
            _("You are currently in: {}, did you perhaps intend another directory?".format(cwd))
        ))
        self.payload.update(files=files, dir=cwd)


class InvalidConfigError(Error):
    pass

class MissingToolError(InvalidConfigError):
    pass

class TimeoutError(Error):
    pass

class ConnectionError(Error):
    pass

class InvalidSignatureError(Error):
    pass
