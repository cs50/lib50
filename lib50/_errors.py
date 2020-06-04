import os
from . import _

__all__ = ["Error", "InvalidSlugError", "MissingFilesError", "InvalidConfigError", "MissingToolError", "TimeoutError", "ConnectionError"]

class Error(Exception):
    """
    A generic lib50 Error.

    :ivar dict payload: arbitrary data

    """
    def __init__(self, *args, **kwargs):
        """"""
        super().__init__(*args, **kwargs)
        self.payload = {}

class InvalidSlugError(Error):
    """A ``lib50.Error`` signalling that a slug is invalid."""
    pass

class MissingFilesError(Error):
    """
    A ``ib50.Error`` signalling that files are missing.
    This error's payload has a ``files`` and ``dir`` key.
    ``MissingFilesError.payload["files"]`` are all the missing files in a list of strings.
    ``MissingFilesError.payload["dir"]`` is the current working directory (cwd) from when this error was raised.
    """
    def __init__(self, files):
        """
        :param files: the missing files that caused the error
        :type files: list of string(s) or Pathlib.path(s)
        """
        cwd = os.getcwd().replace(os.path.expanduser("~"), "~", 1)
        super().__init__("{}\n{}\n{}".format(
            _("You seem to be missing these required files:"),
            "\n".join(files),
            _("You are currently in: {}, did you perhaps intend another directory?".format(cwd))
        ))
        self.payload.update(files=files, dir=cwd)


class InvalidConfigError(Error):
    """A ``lib50.Error`` signalling that a config is invalid."""
    pass

class MissingToolError(InvalidConfigError):
    """A more specific ``lib50.InvalidConfigError`` signalling that an entry for a tool is missing in the config."""
    pass

class TimeoutError(Error):
    """A ``lib50.Error`` signalling a timeout has occured."""
    pass

class ConnectionError(Error):
    """A ``lib50.Error`` signalling a connection has errored."""
    pass

class InvalidSignatureError(Error):
    """A ``lib50.Error`` signalling the signature of a payload is invalid."""
    pass
