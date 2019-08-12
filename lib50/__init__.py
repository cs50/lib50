import pathlib as _pathlib
import gettext as _gettext
import pkg_resources as _pkg_resources

# Internationalization
_ = _gettext.translation("lib50", _pkg_resources.resource_filename("lib50", "locale"), fallback=True).gettext

_LOCAL_PATH = _pathlib.Path("~/.local/share/lib50").expanduser().absolute()


def get_local_path():
    return _LOCAL_PATH


def set_local_path(path):
    global _LOCAL_PATH
    _LOCAL_PATH = _pathlib.Path(path).expanduser().absolute()


from ._api import *
from ._errors import *
from . import config, crypto
