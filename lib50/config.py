import enum
import yaml
import collections
from . import errors
from . import _

try:
    from yaml import CSafeLoader as SafeLoader
except ImportError:
    from yaml import SafeLoader


class TaggedValue:
    def __init__(self, value, tag, *tags):
        for t in tags:
            setattr(self, t[1:], False)
        setattr(self, tag[1:], True)
        self.tag = tag
        self.tags = set(tags)
        self.value = value

    def __repr__(self):
        return f"TaggedValue(tag={self.tag}, tags={self.tags})"


class Loader:
    def __init__(self, tool, *global_tags, default=None):
        self._global_tags = self._ensure_exclamation(global_tags)
        self._global_default = default if not default or default.startswith("!") else "!" + default
        self._scopes = collections.defaultdict(list)
        self.tool = tool

    def scope(self, key, *tags, default=None):
        """Only apply tags and default for top-level key, effectively scoping the tags."""
        scope = self._scopes[key]
        tags = self._ensure_exclamation(tags)
        default = default if not default or default.startswith("!") else "!" + default

        if scope:
            scope[0] = scope[0] + tags
            scope[1] = default if default else scope[1]
        else:
            scope.append(tags)
            scope.append(default)

    def load(self, content):
        """Parse yaml content."""
        # Try parsing the YAML with global tags
        try:
            config = yaml.load(content, Loader=self._loader(self._global_tags))
        except yaml.YAMLError:
            raise errors.InvalidConfigError(_("Config is not valid yaml."))

        # Try extracting just the tool portion
        try:
            config = config[self.tool]
        except (TypeError, KeyError):
            return None

        # If no scopes, just apply global default
        if not isinstance(config, dict):
            config = self._apply_default(config, self._global_default)
        else:
            # Figure out what scopes exist
            scoped_keys = set(key for key in self._scopes)

            # For every scope
            for key in config:
                # If scope has custom tags, apply
                if key in scoped_keys:
                    # local tags, and local default
                    tags, default = self._scopes[key]

                    # Inherit global default if no local default
                    if not default:
                        default = self._global_default

                    config[key] = self._apply_default(config[key], default)
                    self._apply_scope(config[key], tags)
                # Otherwise just apply global default
                else:
                    config[key] = self._apply_default(config[key], self._global_default)

        self._validate(config)

        return config

    def _loader(self, tags):
        """Create a yaml Loader."""
        class ConfigLoader(SafeLoader):
            pass
        ConfigLoader.add_multi_constructor("", lambda loader, prefix, node: TaggedValue(node.value, node.tag, *tags))
        return ConfigLoader

    def _validate(self, config):
        """Check whether every TaggedValue has a valid tag, otherwise raise InvalidConfigError"""
        if isinstance(config, dict):
            # Recursively validate each item in the config
            for val in config.values():
                self._validate(val)

        elif isinstance(config, list):
            # Recursively validate each item in the config
            for item in config:
                self._validate(item)

        elif isinstance(config, TaggedValue):
            tagged_value = config

            # if tagged_value is invalid, error
            if tagged_value.tag not in tagged_value.tags:
                raise errors.InvalidConfigError(_("{} is not a valid tag for {}".format(tagged_value.tag, self.tool)))

    def _apply_default(self, config, default):
        """
        Apply default value to every str in config.
        Also ensure every TaggedValue has default in .tags
        """
        # No default, nothing to be done here
        if not default:
            return config

        # If the entire config is just a string, return default TaggedValue
        if isinstance(config, str):
            return TaggedValue(config, default, default, *self._global_tags)

        if isinstance(config, dict):
            # Recursively apply defaults for  each item in the config
            for key, val in config.items():
                config[key] = self._apply_default(val, default)

        elif isinstance(config, list):
            # Recursively apply defaults for each item in the config
            for i, val in enumerate(config):
                config[i] = self._apply_default(val, default)

        elif isinstance(config, TaggedValue):
            # Make sure each TaggedValue knows about the default tag
            config.tags.add(default)

        return config

    def _apply_scope(self, config, tags):
        """Add locally scoped tags to config"""
        if isinstance(config, dict):
            # Recursively _apply_scope for each item in the config
            for val in config.values():
                self._apply_scope(val, tags)

        elif isinstance(config, list):
            # Recursively _apply_scope for each item in the config
            for item in config:
                self._apply_scope(item, tags)

        elif isinstance(config, TaggedValue):
            # add all local tags
            config.tags |= set(tags)

    @staticmethod
    def _ensure_exclamation(tags):
        return [tag if tag.startswith("!") else "!" + tag for tag in tags]


class InvalidTag:
    """Class representing unrecognized tags"""
    def __init__(self, loader, prefix, node):
        self.tag = node.tag


class PatternType(enum.Enum):
    Excluded = "!exclude"
    Included = "!include"
    Required = "!require"


class FilePattern:
    """Class representing valid file pattern tags"""
    def __init__(self, pattern_type, pattern):
        self.type = pattern_type
        self.pattern = pattern


class ConfigLoader(SafeLoader):
    pass


# Register FilePattern object for !require/!include/!exclude tags
for member in PatternType.__members__.values():
    ConfigLoader.add_constructor(member.value, lambda loader, node : FilePattern(PatternType(node.tag), node.value))

# Register InvalidTag for all other tags
ConfigLoader.add_multi_constructor("", InvalidTag)


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
        # Recursively validate each item in the config
        for val in config.values():
            _validate_config(val, tool)

    elif isinstance(config, list):
        # Recursively validate each item in the config
        for item in config:
            _validate_config(item, tool)

    elif isinstance(config, InvalidTag):
        raise errors.InvalidConfigError(_("{} is not a valid tag for {}".format(config.tag, tool)))
