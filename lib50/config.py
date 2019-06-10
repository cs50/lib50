import enum
import yaml
import os
import pathlib
from . import errors
from . import _

try:
    from yaml import CSafeLoader as SafeLoader
except ImportError:
    from yaml import SafeLoader


class InvalidTag:
    def __init__(self, loader, prefix, node):
        self.tag = node.tag


class PatternType(enum.Enum):
    Excluded = "!exclude"
    Included = "!include"
    Required = "!require"


class FilePattern:
    def __init__(self, pattern_type, pattern):
        self.type = pattern_type
        self.pattern = pattern


class ConfigLoader(SafeLoader):
    pass


for member in PatternType.__members__.values():
    ConfigLoader.add_constructor(member.value, lambda loader, node : FilePattern(PatternType(node.tag), node.value))
ConfigLoader.add_multi_constructor("", InvalidTag)


def get_config_filepath(path):
    """
    Looks for the following files in order at path:
        - .cs50.yaml
        - .cs50.yml
    If either exists,
        returns path to that file (i.e. <path>/.cs50.yaml or <path>/.cs50.yml)
    Raises errors.Error otherwise.
    """
    path = pathlib.Path(path)

    if (path / ".cs50.yaml").exists():
        return path / ".cs50.yaml"

    if (path / ".cs50.yml").exists():
        return path / ".cs50.yml"

    raise errors.Error(_("No config file (.cs50.yaml or .cs50.yml) found at {}".format(path)))


def load(content, tool, loader=ConfigLoader):
    """
    Parses content (contents of .cs50.yaml) with lib50.config.ConfigLoader
    Raises InvalidConfigError
    """
    try:
        config = yaml.load(content, Loader=loader)
    except yaml.YAMLError:
        raise errors.InvalidConfigError(_("Config is not valid yaml."))

    try:
        config = config[tool]
    except (TypeError, KeyError):
        config = None

    try:
        files = config["files"]
    except (TypeError, KeyError):
        pass
    else:
        if not isinstance(files, list):
            raise errors.InvalidConfigError(_("files: entry in config must be a list"))

        for file in files:
            if not isinstance(file, FilePattern):
                raise errors.InvalidConfigError(
                    _("All entries in files: must be tagged with either !include, !exclude or !require"))

    _validate_config(config, tool)

    return config

def _validate_config(config, tool):
    if isinstance(config, dict):
        for item in config:
            _validate_config(config[item], tool)

    elif isinstance(config, list):
        for item in config:
            _validate_config(item, tool)

    elif isinstance(config, InvalidTag):
        raise errors.InvalidConfigError("{} is not a valid tag for {}".format(config.tag, tool))
