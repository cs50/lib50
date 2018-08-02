import os
from . import _

class Error(Exception):
    pass

class InvalidSlugError(Error):
    pass

class MissingFilesError(Error):
    def __init__(self, files):
        super().__init__("{}\n{}\n{}".format(
            _("You seem to be missing these required files:"),
            "\n".join(files),
            _("You are currently in: {}, did you perhaps intend another directory?".format(os.getcwd()))
        ))

class InvalidConfigError(Error):
    pass
