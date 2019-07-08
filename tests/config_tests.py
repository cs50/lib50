import sys
import unittest
import tempfile
import os
import pathlib

import lib50._errors
import lib50.config

class TestLoader(unittest.TestCase):
    def test_no_tool(self):
        content = ""
        with self.assertRaises(lib50._errors.MissingToolError):
            config = lib50.config.Loader("check50").load(content)

    def test_falsy_tool(self):
        content = "check50: false"
        config = lib50.config.Loader("check50").load(content)
        self.assertFalse(config)

    def test_truthy_tool(self):
        content = "check50: true"
        config = lib50.config.Loader("check50").load(content)
        self.assertTrue(config)

    def test_no_files(self):
        content = \
            "check50:\n" \
            "  dependencies:\n" \
            "    - foo"
        config = lib50.config.Loader("check50").load(content)
        self.assertEqual(config, {"dependencies" : ["foo"]})

    def test_no_validation(self):
        content = \
            "check50:\n" \
            "  bar:\n" \
            "    - !include foo"
        config = lib50.config.Loader("check50").load(content, validate=False)
        self.assertEqual(config["bar"][0].tag, "include")
        self.assertEqual(config["bar"][0].value, "foo")

    def test_global_tag(self):
        content = \
            "check50:\n" \
            "  foo:\n" \
            "    - !include baz\n" \
            "  bar:\n" \
            "    - !include qux"
        config = lib50.config.Loader("check50", "include").load(content)
        self.assertEqual(config["foo"][0].tag, "include")
        self.assertEqual(config["foo"][0].value, "baz")
        self.assertEqual(config["bar"][0].tag, "include")
        self.assertEqual(config["bar"][0].value, "qux")

    def test_local_tag(self):
        content = \
            "check50:\n" \
            "  files:\n" \
            "    - !include foo"
        loader = lib50.config.Loader("check50")
        loader.scope("files", "include")
        config = loader.load(content)
        self.assertEqual(config["files"][0].tag, "include")
        self.assertEqual(config["files"][0].value, "foo")

        content = \
            "check50:\n" \
            "  bar:\n" \
            "    - !include foo"
        loader = lib50.config.Loader("check50")
        loader.scope("files", "include", default=False)
        with self.assertRaises(lib50._errors.InvalidConfigError):
            config = loader.load(content)

    def test_no_default(self):
        content = \
            "check50:\n" \
            "  files:\n" \
            "    - !INVALID foo"
        loader = lib50.config.Loader("check50")
        loader.scope("files", "include", default=False)
        with self.assertRaises(lib50._errors.InvalidConfigError):
            config = loader.load(content)

    def test_local_default(self):
        content = \
            "check50:\n" \
            "  files:\n" \
            "    - foo"
        loader = lib50.config.Loader("check50")
        loader.scope("files", default="bar")
        config = loader.load(content)
        self.assertEqual(config["files"][0].tag, "bar")
        self.assertEqual(config["files"][0].value, "foo")

    def test_global_default(self):
        content = \
            "check50:\n" \
            "  files:\n" \
            "    - foo"
        config = lib50.config.Loader("check50", default="bar").load(content)
        self.assertEqual(config["files"][0].tag, "bar")
        self.assertEqual(config["files"][0].value, "foo")

    def test_multiple_defaults(self):
        content = \
            "check50:\n" \
            "  foo:\n" \
            "    - baz\n" \
            "  bar:\n" \
            "    - qux"
        loader = lib50.config.Loader("check50", default="include")
        loader.scope("bar", default="exclude")
        config = loader.load(content)
        self.assertEqual(config["foo"][0].tag, "include")
        self.assertEqual(config["foo"][0].value, "baz")
        self.assertEqual(config["bar"][0].tag, "exclude")
        self.assertEqual(config["bar"][0].value, "qux")

    def test_same_tag_default(self):
        content = \
            "check50:\n" \
            "  foo:\n" \
            "    - !include bar\n" \
            "    - baz"
        config = lib50.config.Loader("check50", "include", default="include").load(content)
        self.assertEqual(config["foo"][0].tag, "include")
        self.assertEqual(config["foo"][0].value, "bar")
        self.assertEqual(config["foo"][1].tag, "include")
        self.assertEqual(config["foo"][1].value, "baz")

    def test_multiple_tools(self):
        content = \
            "check50:\n" \
            "  files:\n" \
            "    - !require foo\n" \
            "lab50:\n" \
            "  files:\n" \
            "    - !open bar"

        check50_loader = lib50.config.Loader("check50")
        check50_loader.scope("files", "require")
        config = check50_loader.load(content)
        self.assertEqual(config["files"][0].tag, "require")
        self.assertEqual(config["files"][0].value, "foo")

        lab50_loader = lib50.config.Loader("lab50")
        lab50_loader.scope("files", "open")
        config = lab50_loader.load(content)
        self.assertEqual(config["files"][0].tag, "open")
        self.assertEqual(config["files"][0].value, "bar")


class TestGetConfigFilepath(unittest.TestCase):
    def setUp(self):
        self.working_directory = tempfile.TemporaryDirectory()
        self.old_cwd = os.getcwd()
        os.chdir(self.working_directory.name)

    def tearDown(self):
        self.working_directory.cleanup()
        os.chdir(self.old_cwd)

    def test_no_config(self):
        with self.assertRaises(lib50._errors.Error):
            lib50.config.get_config_filepath(os.getcwd())

        with open("foo.txt", "w"):
            pass

        with self.assertRaises(lib50._errors.Error):
            lib50.config.get_config_filepath(os.getcwd())

    def test_config_yml(self):
        with open(".cs50.yml", "w"):
            pass

        config_file = lib50.config.get_config_filepath(os.getcwd())

        self.assertEqual(config_file, pathlib.Path(os.getcwd()) / ".cs50.yml")

    def test_config_yaml(self):
        with open(".cs50.yaml", "w"):
            pass

        config_file = lib50.config.get_config_filepath(os.getcwd())

        self.assertEqual(config_file, pathlib.Path(os.getcwd()) / ".cs50.yaml")

    def test_multiple_configs(self):
        with open(".cs50.yaml", "w"):
            pass

        with open(".cs50.yml", "w"):
            pass

        with self.assertRaises(lib50.Error):
            config_file = lib50.config.get_config_filepath(os.getcwd())


if __name__ == '__main__':
    suite = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])
    unittest.TextTestRunner(verbosity=2).run(suite)
