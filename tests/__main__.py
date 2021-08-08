import logging
import unittest
import sys
import termcolor

from . import *

import lib50._api as api

class ColoredFormatter(logging.Formatter):
    COLORS = {
        "ERROR": "red",
        "WARNING": "yellow",
        "DEBUG": "cyan",
        "INFO": "magenta",
    }

    def __init__(self, fmt, use_color=True):
        super().__init__(fmt=fmt)
        self.use_color = use_color

    def format(self, record):
        msg = super().format(record)
        return msg if not self.use_color else termcolor.colored(msg, getattr(record, "color", self.COLORS.get(record.levelname)))

api.logger.setLevel("DEBUG")
handler = logging.StreamHandler(sys.stderr)
handler.setFormatter(ColoredFormatter("(%(levelname)s) %(message)s", use_color=sys.stderr.isatty()))
api.logger.addHandler(handler)

suite = unittest.TestLoader().discover("tests", pattern="*_tests.py")
result = unittest.TextTestRunner(verbosity=2).run(suite)
sys.exit(bool(result.errors or result.failures))
