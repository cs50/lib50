import unittest
import sys

from . import *

import lib50._api as api

api.logger.setLevel("DEBUG")

suite = unittest.TestLoader().discover("tests", pattern="*_tests.py")
result = unittest.TextTestRunner(verbosity=2).run(suite)
sys.exit(bool(result.errors or result.failures))
