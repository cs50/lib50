import unittest
import tempfile
import os
import pathlib
import lib50.config

class TestLoad(unittest.TestCase):
    def test_no_tool(self):
        content = ""
        config = lib50.config.load(content, "check50")
        self.assertEqual(config, None)

    def test_falsy_tool(self):
        content = "check50: false"
        config = lib50.config.load(content, "check50")
        self.assertFalse(config)

    def test_truthy_tool(self):
        content = "check50: true"
        config = lib50.config.load(content, "check50")
        self.assertTrue(config)

    def test_no_files(self):
        content = \
            "check50:\n" \
            "  dependencies:\n" \
            "    - foo"
        config = lib50.config.load(content, "check50")
        self.assertEqual(config, {"dependencies" : ["foo"]})

    def test_include_file(self):
        content = \
            "check50:\n" \
            "  files:\n" \
            "    - !include foo"
        config = lib50.config.load(content, "check50")
        self.assertTrue(config["files"][0].type == lib50.config.PatternType.Included)

    def test_exclude_file(self):
        content = \
            "check50:\n" \
            "  files:\n" \
            "    - !exclude foo"
        config = lib50.config.load(content, "check50")
        self.assertTrue(config["files"][0].type == lib50.config.PatternType.Excluded)

    def test_require_file(self):
        content = \
            "check50:\n" \
            "  files:\n" \
            "    - !require foo"
        config = lib50.config.load(content, "check50")
        self.assertTrue(config["files"][0].type == lib50.config.PatternType.Required)


class TestGetConfigFilepath(unittest.TestCase):
    def setUp(self):
        self.working_directory = tempfile.TemporaryDirectory()
        self.old_cwd = os.getcwd()
        os.chdir(self.working_directory.name)

    def tearDown(self):
        self.working_directory.cleanup()
        os.chdir(self.old_cwd)

    def test_no_config(self):
        with self.assertRaises(lib50.errors.Error):
            lib50.config.get_config_filepath(os.getcwd())

        with open("foo.txt", "w"):
            pass

        with self.assertRaises(lib50.errors.Error):
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

    def test_config_order(self):
        with open(".cs50.yaml", "w"):
            pass

        with open(".cs50.yml", "w"):
            pass

        config_file = lib50.config.get_config_filepath(os.getcwd())

        self.assertEqual(config_file, pathlib.Path(os.getcwd()) / ".cs50.yaml")


if __name__ == '__main__':
    unittest.main()
