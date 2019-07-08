import gettext
import pkg_resources

# Internationalization
_ = gettext.translation("lib50", pkg_resources.resource_filename("lib50", "locale"), fallback=True).gettext

from .api import *
from .errors import *
from . import config
