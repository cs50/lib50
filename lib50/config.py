import collections
import enum

import yaml
import os
import pathlib
from ._errors import InvalidConfigError, Error, MissingToolError
from . import _

try:
    from yaml import CSafeLoader as SafeLoader
except ImportError:
    from yaml import SafeLoader


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

    yaml_path = path / ".cs50.yaml" if (path / ".cs50.yaml").exists() else None
    yml_path = path / ".cs50.yml" if (path / ".cs50.yml").exists() else None

    if yaml_path and yml_path:
        raise Error(_("Two config files (.cs50.yaml and .cs50.yml) found at {}").format(path))

    if not yaml_path and not yml_path:
        raise Error(_("No config file (.cs50.yaml or .cs50.yml) found at {}".format(path)))

    return yml_path or yaml_path


class TaggedValue:
    """A value tagged in a .yaml file"""
    def __init__(self, value, tag):
        self.value = value
        self.tag = tag[1:] if tag.startswith("!") else tag

    def __repr__(self):
        return f"TaggedValue(value={self.value}, tag={self.tag})"


class Loader:
    class _TaggedYamlValue:
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
            return f"_TaggedYamlValue(tag={self.tag}, tags={self.tags})"


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

    def load(self, content, validate=True):
        """Parse yaml content."""
        # Try parsing the YAML with global tags
        try:
            config = yaml.load(content, Loader=self._loader(self._global_tags))
        except yaml.YAMLError:
            raise InvalidConfigError(_("Config is not valid yaml."))

        # Try extracting just the tool portion
        try:
            config = config[self.tool]
            assert config
        except (TypeError, KeyError, AssertionError):
            raise MissingToolError("{} is not enabled by this config file.".format(self.tool))

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

        if validate:
            self._validate_tags(config)

        config = self._simplify(config)

        return config

    def _loader(self, tags):
        """Create a yaml Loader."""
        class ConfigLoader(SafeLoader):
            pass
        ConfigLoader.add_multi_constructor("", lambda loader, prefix, node: Loader._TaggedYamlValue(node.value, node.tag, *tags))
        return ConfigLoader

    def _simplify(self, config):
        """Replace all Loader._TaggedYamlValue with TaggedValue (a simpler datastructure)"""
        if isinstance(config, dict):
            # Recursively simplify for each item in the config
            for key, val in config.items():
                config[key] = self._simplify(val)

        elif isinstance(config, list):
            # Recursively simplify for each item in the config
            for i, val in enumerate(config):
                config[i] = self._simplify(val)

        elif isinstance(config, Loader._TaggedYamlValue):
            # Replace Loader._TaggedYamlValue with TaggedValue
            config = TaggedValue(config.value, config.tag)

        return config

    def _validate_tags(self, config):
        """Check whether every _TaggedYamlValue has a valid tag, otherwise raise InvalidConfigError"""
        if isinstance(config, dict):
            # Recursively validate each item in the config
            for val in config.values():
                self._validate_tags(val)

        elif isinstance(config, list):
            # Recursively validate each item in the config
            for item in config:
                self._validate_tags(item)

        elif isinstance(config, Loader._TaggedYamlValue):
            tagged_value = config

            # if tagged_value is invalid, error
            if tagged_value.tag not in tagged_value.tags:
                raise InvalidConfigError(_("{} is not a valid tag for {}".format(tagged_value.tag, self.tool)))

    def _apply_default(self, config, default):
        """
        Apply default value to every str in config.
        Also ensure every _TaggedYamlValue has default in .tags
        """
        # No default, nothing to be done here
        if not default:
            return config

        # If the entire config is just a string, return default _TaggedYamlValue
        if isinstance(config, str):
            return Loader._TaggedYamlValue(config, default, default, *self._global_tags)

        if isinstance(config, dict):
            # Recursively apply defaults for  each item in the config
            for key, val in config.items():
                config[key] = self._apply_default(val, default)

        elif isinstance(config, list):
            # Recursively apply defaults for each item in the config
            for i, val in enumerate(config):
                config[i] = self._apply_default(val, default)

        elif isinstance(config, Loader._TaggedYamlValue):
            # Make sure each _TaggedYamlValue knows about the default tag
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

        elif isinstance(config, Loader._TaggedYamlValue):
            tagged_value = config

            # add all local tags
            tagged_value.tags |= set(tags)
            for tag in tags:
                if not hasattr(tagged_value, tag):
                    setattr(tagged_value, tag, False)

    @staticmethod
    def _ensure_exclamation(tags):
        return [tag if tag.startswith("!") else "!" + tag for tag in tags]
