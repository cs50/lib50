import collections
import enum

import yaml

from ._errors import InvalidConfigError
from . import _

try:
    from yaml import CSafeLoader as SafeLoader
except ImportError:
    from yaml import SafeLoader


class TaggedValue:
    """A value tagged in a .yaml file"""

    def __init__(self, value, tag, *tags):
        """
        value - the actual value
        tag - the yaml tag
        tags - all possible valid tags for this value
        """
        tag = tag if tag.startswith("!") else "!" + tag

        tags = list(tags)
        for i, t in enumerate(tags):
            tags[i] = t if t.startswith("!") else "!" + t
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
            raise InvalidConfigError(_("Config is not valid yaml."))

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
                raise InvalidConfigError(_("{} is not a valid tag for {}".format(tagged_value.tag, self.tool)))

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
            tagged_value = config

            # add all local tags
            tagged_value.tags |= set(tags)
            for tag in tags:
                if not hasattr(tagged_value, tag):
                    setattr(tagged_value, tag, False)

    @staticmethod
    def _ensure_exclamation(tags):
        return [tag if tag.startswith("!") else "!" + tag for tag in tags]
