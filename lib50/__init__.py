import gettext as _gettext
import pkg_resources as _pkg_resources

# Internationalization
_ = _gettext.translation("lib50", _pkg_resources.resource_filename("lib50", "locale"), fallback=True).gettext

LOCAL_PATH = "~/.local/share/lib50"

from ._api import *
from ._errors import *
from . import config
