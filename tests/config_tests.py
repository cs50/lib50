import unittest
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
        self.assertTrue(config["files"][0].status == lib50.config.FileStatus.Included)

    def test_exclude_file(self):
        content = \
            "check50:\n" \
            "  files:\n" \
            "    - !exclude foo"
        config = lib50.config.load(content, "check50")
        self.assertTrue(config["files"][0].status == lib50.config.FileStatus.Excluded)

    def test_require_file(self):
        content = \
            "check50:\n" \
            "  files:\n" \
            "    - !require foo"
        config = lib50.config.load(content, "check50")
        self.assertTrue(config["files"][0].status == lib50.config.FileStatus.Required)

if __name__ == '__main__':
    unittest.main()
