import datetime
import os
from . import _

__all__ = [
    "Error",
    "InvalidSlugError",
    "MissingFilesError",
    "TooManyFilesError",
    "InvalidBranchError",
    "InvalidConfigError",
    "MissingToolError",
    "TimeoutError",
    "ConnectionError",
    "RejectedHonestyPromptError",
    "InvalidTokenError",
    "RateLimitError"
]


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
    A ``lib50.Error`` signaling that files are missing.
    This error's payload has a ``files`` and ``dir`` key.
    ``MissingFilesError.payload["files"]`` are all the missing files in a list of strings.
    ``MissingFilesError.payload["dir"]`` is the current working directory (cwd) from when this error was raised.
    """

    def __init__(self, files, dir=None):
        """
        :param files: the missing files that caused the error
        :type files: list of string(s) or Pathlib.path(s)
        """
        if dir is None:
            dir = os.path.expanduser(os.getcwd())

        super().__init__("{}\n{}\n{}".format(
            _("You seem to be missing these required files:"),
            "\n".join(files),
            _("You are currently in: {}, did you perhaps intend another directory?".format(dir))
        ))
        self.payload.update(files=files, dir=dir)


class TooManyFilesError(Error):
    """
    A ``lib50.Error`` signaling that too many files were attempted to be included.
    The error's payload has a ``dir`` and a ``limit`` key.
    ``TooManyFilesError.payload["dir"]`` is the directory in which the attempted submission occured.
    ``TooManyFilesError.payload["limit"]`` is the max number of files allowed
    """

    def __init__(self, limit, dir=None):

        if dir is None:
            dir = os.path.expanduser(os.getcwd())

        super().__init__("{}\n{}".format(
            _("Looks like you are in a directory with too many (> {}) files.").format(limit),
            _("You are currently in: {}, did you perhaps intend another directory?".format(dir))
        ))
        self.payload.update(limit=limit, dir=dir)


class InvalidBranchError(Error):
    """A ``lib50.Error`` signalling that a branch prefix is invalid."""
    pass


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


class RejectedHonestyPromptError(Error):
    """A ``lib50.Error`` signalling the honesty prompt was rejected by the user."""
    pass


class InvalidTokenError(Error):
    """A ``lib50.Error`` signalling that the GitHub token is invalid or expired."""
    pass


class RateLimitError(Error):
    """
    A ``lib50.Error`` signalling the GitHub API rate limit is exhausted.
    Unlike ``InvalidTokenError`` the token is valid, so the remedy is to wait, not to
    re-authenticate.
    ``RateLimitError.payload["reset"]`` is the UNIX timestamp when the budget resets, if known.
    ``RateLimitError.payload["user_id"]`` and ``["request_id"]`` identify the account and the
    GitHub request, when GitHub reported them.
    """

    def __init__(self, reset=None, user_id=None, request_id=None):
        message = _("You have reached GitHub's hourly API rate limit.")
        if reset:
            try:
                when = datetime.datetime.fromtimestamp(int(reset)).strftime("%H:%M")
                message = _("You have reached GitHub's hourly API rate limit."
                            " Please try again after {}.").format(when)
            except (TypeError, ValueError):
                pass
        super().__init__(message)
        self.payload.update(reset=reset, user_id=user_id, request_id=request_id)
