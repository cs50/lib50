import unittest
import os
import io
import time
import pathlib
import contextlib
import shutil
import sys
import tempfile
import logging
import termcolor
import subprocess
import lib50
import lib50.config

class TestConnect(unittest.TestCase):
    def setUp(self):
        self.loader = lib50.config.Loader("check50")
        self.loader.scope("files", "exclude", "include", "require")

        self.working_directory = tempfile.TemporaryDirectory()
        self._wd = os.getcwd()
        os.chdir(self.working_directory.name)

    def tearDown(self):
        self.working_directory.cleanup()
        os.chdir(self._wd)

    def test_connect(self):
        f = io.StringIO()
        open("hello.py", "w").close()
        with contextlib.redirect_stdout(f):
            org, (included, excluded) = lib50.connect("cs50/problems2/foo/bar", self.loader)
            self.assertEqual(excluded, set())

            self.assertEqual(org, "check50")
        self.assertTrue("Connecting..." in f.getvalue())

        f = io.StringIO()
        loader = lib50.config.Loader("submit50")
        loader.scope("files", "exclude", "include", "require")
        with contextlib.redirect_stdout(f):
            include, excluded = lib50.connect("cs50/problems2/foo/bar", loader)
            self.assertEqual(included, {"hello.py"})
        self.assertTrue("Connecting..." in f.getvalue())

    def test_missing_problem(self):
        f = io.StringIO()
        with contextlib.redirect_stdout(f):
            with self.assertRaises(lib50.InvalidSlugError):
                lib50.connect("cs50/problems2/foo/i_do_not_exist", self.loader)

    def test_no_tool_in_config(self):
        f = io.StringIO()
        with contextlib.redirect_stdout(f):
            with self.assertRaises(lib50.InvalidSlugError):
                loader = lib50.config.Loader("i_do_not_exist")
                lib50.connect("cs50/problems2/foo/bar", loader)

    def test_no_config(self):
        f = io.StringIO()
        with contextlib.redirect_stdout(f):
            with self.assertRaises(lib50.InvalidSlugError):
                lib50.connect("cs50/problems2/foo/no_config", self.loader)

class TestFiles(unittest.TestCase):
    def setUp(self):
        self.loader = lib50.config.Loader("check50")
        self.loader.scope("files", "include", "exclude", "require")

        self.working_directory = tempfile.TemporaryDirectory()
        self._wd = os.getcwd()
        os.chdir(self.working_directory.name)

    def tearDown(self):
        self.working_directory.cleanup()
        os.chdir(self._wd)

    def test_exclude_only_one(self):
        content = \
            "check50:\n" \
            "  files:\n" \
            "    - !exclude foo.py\n"

        config = self.loader.load(content)

        open("foo.py", "w").close()
        open("bar.py", "w").close()

        included, excluded = lib50.files(config.get("files"))
        self.assertEqual(set(included), {"bar.py"})
        self.assertEqual(set(excluded), {"foo.py"})

    def test_exclude_all(self):
        content = \
            "check50:\n" \
            "  files:\n" \
            "    - !exclude \"*\"\n"

        config = self.loader.load(content)

        included, excluded = lib50.files(config.get("files"))
        self.assertEqual(included, set())
        self.assertEqual(excluded, set())

        open("foo.py", "w").close()

        included, excluded = lib50.files(config.get("files"))
        self.assertEqual(set(included), set())
        self.assertEqual(set(excluded), {"foo.py"})

    def test_include_only_one(self):
        content = \
            "check50:\n" \
            "  files:\n" \
            "    - !exclude \"*\"\n" \
            "    - !include foo.py\n"

        config = self.loader.load(content)

        open("foo.py", "w").close()
        open("bar.py", "w").close()

        included, excluded = lib50.files(config.get("files"))
        self.assertEqual(set(included), {"foo.py"})
        self.assertEqual(set(excluded), {"bar.py"})

    def test_include_all(self):
        config = {}

        open("foo.py", "w").close()
        open("bar.c", "w").close()

        included, excluded = lib50.files(config.get("files"))
        self.assertEqual(set(included), {"foo.py", "bar.c"})
        self.assertEqual(set(excluded), set())

        content = \
            "check50:\n" \
            "  files:\n" \
            "    - !include \"*\"\n"

        config = self.loader.load(content)

        included, excluded = lib50.files(config.get("files"))
        self.assertEqual(set(included), {"foo.py", "bar.c"})
        self.assertEqual(set(excluded), set())

    def test_required(self):
        content = \
            "check50:\n" \
            "  files:\n" \
            "    - !require foo.py\n"

        config = self.loader.load(content)

        open("foo.py", "w").close()

        included, excluded = lib50.files(config.get("files"))
        self.assertEqual(set(included), {"foo.py"})
        self.assertEqual(set(excluded), set())

        open("bar.c", "w").close()

        included, excluded = lib50.files(config.get("files"))
        self.assertEqual(set(included), {"foo.py", "bar.c"})
        self.assertEqual(set(excluded), set())

    def test_required_overwrite_exclude(self):
        content = \
            "check50:\n" \
            "  files:\n" \
            "    - !exclude \"*\"\n" \
            "    - !require foo.py\n"

        config = self.loader.load(content)

        open("foo.py", "w").close()

        included, excluded = lib50.files(config.get("files"))
        self.assertEqual(set(included), {"foo.py"})
        self.assertEqual(set(excluded), set())

        open("bar.c", "w").close()

        included, excluded = lib50.files(config.get("files"))
        self.assertEqual(set(included), {"foo.py"})
        self.assertEqual(set(excluded), {"bar.c"})

    def test_always_exclude(self):
        content = \
            "check50:\n" \
            "  files:\n" \
            "    - !include foo.py\n"

        config = self.loader.load(content)

        open("foo.py", "w").close()

        included, excluded = lib50.files(config.get("files"), always_exclude=["foo.py"])
        self.assertEqual(set(included), set())
        self.assertEqual(set(excluded), set())

    def test_exclude_folder_include_file(self):
        content = \
            "check50:\n" \
            "  files:\n" \
            "    - !exclude foo\n" \
            "    - !include foo/bar\n"

        config = self.loader.load(content)

        os.mkdir("foo")
        open("foo/bar", "w").close()

        included, excluded = lib50.files(config.get("files"))
        self.assertEqual(set(included), {"foo/bar"})
        self.assertEqual(set(excluded), set())

    def test_include_file_exclude_folder(self):
        content = \
            "check50:\n" \
            "  files:\n" \
            "    - !include foo/bar.py\n" \
            "    - !exclude foo\n"

        config = self.loader.load(content)

        os.mkdir("foo")
        open("foo/bar.py", "w").close()

        included, excluded = lib50.files(config.get("files"))
        self.assertEqual(set(included), set())
        self.assertEqual(set(excluded), {"foo/bar.py"})

    def test_exclude_extension_include_folder(self):
        content = \
            "check50:\n" \
            "  files:\n" \
            "    - !exclude \"*.py\"\n" \
            "    - !include foo\n"

        config = self.loader.load(content)

        os.mkdir("foo")
        open("foo/bar.py", "w").close()

        included, excluded = lib50.files(config.get("files"))
        self.assertEqual(set(included), {"foo/bar.py"})
        self.assertEqual(set(excluded), set())

    def test_exclude_extension_include_everything_from_folder(self):
        content = \
            "check50:\n" \
            "  files:\n" \
            "    - !exclude \"*.py\"\n" \
            "    - !include \"foo/*\"\n"

        config = self.loader.load(content)

        os.mkdir("foo")
        open("foo/bar.py", "w").close()

        included, excluded = lib50.files(config.get("files"))
        self.assertEqual(set(included), {"foo/bar.py"})
        self.assertEqual(set(excluded), set())

    def test_exclude_everything_include_folder(self):
        content = \
            "check50:\n" \
            "  files:\n" \
            "    - !exclude \"*\"\n" \
            "    - !include foo\n"

        config = self.loader.load(content)

        os.mkdir("foo")
        open("foo/bar.py", "w").close()

        included, excluded = lib50.files(config.get("files"))
        self.assertEqual(set(included), {"foo/bar.py"})
        self.assertEqual(set(excluded), set())

    def test_implicit_recursive(self):
        os.mkdir("foo")
        open("foo/bar.py", "w").close()
        open("qux.py", "w").close()

        content = \
            "check50:\n" \
            "  files:\n" \
            "    - !exclude \"*.py\"\n"

        config = self.loader.load(content)

        included, excluded = lib50.files(config.get("files"))
        self.assertEqual(set(included), set())
        self.assertEqual(set(excluded), {"qux.py", "foo/bar.py"})

        content = \
            "check50:\n" \
            "  files:\n" \
            "    - !exclude \"./*.py\"\n"

        config = self.loader.load(content)

        included, excluded = lib50.files(config.get("files"))
        self.assertEqual(set(included), {"foo/bar.py"})
        self.assertEqual(set(excluded), {"qux.py"})

    def test_implicit_recursive_with_slash(self):
        content = \
            "check50:\n" \
            "  files:\n" \
            "    - !exclude \"*/*.py\"\n"

        config = self.loader.load(content)

        os.mkdir("foo")
        os.mkdir("foo/bar")
        open("foo/bar/baz.py", "w").close()
        open("foo/qux.py", "w").close()

        included, excluded = lib50.files(config.get("files"))
        self.assertEqual(set(included), {"foo/bar/baz.py"})
        self.assertEqual(set(excluded), {"foo/qux.py"})

    def test_explicit_recursive(self):
        content = \
            "check50:\n" \
            "  files:\n" \
            "    - !exclude \"foo/**/*.py\"\n"

        config = self.loader.load(content)

        os.mkdir("foo")
        os.mkdir("foo/bar")
        os.mkdir("foo/bar/baz")
        open("foo/bar/baz/qux.py", "w").close()
        open("hello.py", "w").close()

        included, excluded = lib50.files(config.get("files"))
        self.assertEqual(set(included), {"hello.py"})
        self.assertEqual(set(excluded), {"foo/bar/baz/qux.py"})

    def test_requires_no_exclude(self):
        content = \
            "check50:\n" \
            "  files:\n" \
            "    - !require does_not_exist.py\n"

        config = self.loader.load(content)

        with self.assertRaises(lib50.MissingFilesError):
            lib50.files(config.get("files"))

    def test_invalid_utf8_filename(self):
        try:
            open(b"\xc3\x28", "w").close()
        except OSError:
            self.skipTest("can't create invalid utf8 filename")
        else:
            included, excluded = lib50.files({})
            self.assertEqual(included, set())
            self.assertEqual(excluded, {"?("})

    def test_from_root(self):
        os.mkdir("foo")
        os.mkdir("foo/bar")
        os.mkdir("foo/bar/baz")
        open("foo/bar/baz/qux.py", "w").close()
        open("foo/hello.py", "w").close()

        included, excluded = lib50.files([], root="foo")
        self.assertEqual(included, {"bar/baz/qux.py", "hello.py"})
        self.assertEqual(excluded, set())

    def test_no_tags(self):
        open("foo.py", "w").close()
        open("bar.py", "w").close()
        open("baz.py", "w").close()

        content = \
            "check50:\n" \
            "  files:\n" \
            "    - !include \"foo.py\"\n" \
            "    - !exclude \"bar.py\"\n" \
            "    - !require \"baz.py\"\n"
        config = self.loader.load(content)

        included, excluded = lib50.files(config.get("files"), exclude_tags=[], include_tags=[], require_tags=[])

        self.assertEqual(included, {"foo.py", "bar.py", "baz.py"})
        self.assertEqual(excluded, set())

    def test_custom_tags(self):
        open("foo.py", "w").close()
        open("bar.py", "w").close()
        open("baz.py", "w").close()

        content = \
            "foo50:\n" \
            "  files:\n" \
            "    - !open \"foo.py\"\n" \
            "    - !close \"bar.py\"\n" \
            "    - !exclude \"baz.py\"\n"

        loader = lib50.config.Loader("foo50")
        loader.scope("files", "open", "close", "exclude")
        config = loader.load(content)

        included, excluded = lib50.files(config.get("files"),
                                         exclude_tags=["exclude"],
                                         include_tags=[""],
                                         require_tags=["open", "close"])

        self.assertEqual(included, {"foo.py", "bar.py"})
        self.assertEqual(excluded, {"baz.py"})

    def test_non_file_require(self):
        open("foo.py", "w").close()

        content = \
            "check50:\n" \
            "  files:\n" \
            "    - !require \"*.py\"\n"

        config = self.loader.load(content)

        with self.assertRaises(lib50.MissingFilesError):
            included, excluded = lib50.files(config.get("files"))

    def test_lab50_tags(self):
        # Three dummy files
        open("foo.py", "w").close()
        open("bar.py", "w").close()
        open("baz.py", "w").close()

        # Dummy config file (.cs50.yml)
        content = \
            "lab50:\n" \
            "  files:\n" \
            "    - !open \"foo.py\"\n" \
            "    - !include \"bar.py\"\n" \
            "    - !exclude \"baz.py\"\n"

        # Create a config Loader for a tool called lab50
        loader = lib50.config.Loader("lab50")

        # Scope the files section of lab50 with the tags: open, include and exclude
        loader.scope("files", "open", "include", "exclude")

        # Load the config
        config = loader.load(content)

        # Figure out which files have an open tag
        opened_files = [tagged_value.value for tagged_value in config.get("files") if tagged_value.tag == "open"]

        # Have lib50.files figure out which files should be included and excluded
        # Simultaneously ensure all open files exist
        included, excluded = lib50.files(config.get("files"), require_tags=["open"])

        # Make sure that files tagged with open are also included
        opened_files = [file for file in opened_files if file in included]

        # Assert
        self.assertEqual(included, {"foo.py", "bar.py"})
        self.assertEqual(excluded, {"baz.py"})
        self.assertEqual(opened_files, ["foo.py"])


class TestLocal(unittest.TestCase):
    def setUp(self):
        self.loader = lib50.config.Loader("check50")
        self.loader.scope("files", "include", "exclude", "require")

        self.working_directory = tempfile.TemporaryDirectory()
        self._wd = os.getcwd()
        os.chdir(self.working_directory.name)

    def tearDown(self):
        self.working_directory.cleanup()
        os.chdir(self._wd)

    def test_local(self):
        local_dir = lib50.local("cs50/problems2/foo/bar")

        self.assertTrue(local_dir.is_dir())
        self.assertTrue((local_dir / "__init__.py").is_file())
        self.assertTrue((local_dir / ".cs50.yaml").is_file())

        local_dir = lib50.local("cs50/problems2/foo/bar")

        self.assertTrue(local_dir.is_dir())
        self.assertTrue((local_dir / "__init__.py").is_file())
        self.assertTrue((local_dir / ".cs50.yaml").is_file())

        shutil.rmtree(local_dir)

        local_dir = lib50.local("cs50/problems2/foo/bar")

        self.assertTrue(local_dir.is_dir())
        self.assertTrue((local_dir / "__init__.py").is_file())
        self.assertTrue((local_dir / ".cs50.yaml").is_file())

        shutil.rmtree(local_dir)

class TestWorkingArea(unittest.TestCase):
    def setUp(self):
        self.working_directory = tempfile.TemporaryDirectory()
        self._wd = os.getcwd()
        os.chdir(self.working_directory.name)
        with open("foo.py", "w") as f:
            pass

        with open("bar.c", "w") as f:
            pass

        with open("qux.java", "w") as f:
            pass

    def tearDown(self):
        self.working_directory.cleanup()
        os.chdir(self._wd)

    def test_empty(self):
        with lib50.working_area([]) as working_area:
            contents = os.listdir(working_area)

        self.assertEqual(contents, [])

    def test_one_file(self):
        with lib50.working_area(["foo.py"]) as working_area:
            contents = os.listdir(working_area)

        self.assertEqual(contents, ["foo.py"])

    def test_multiple_files(self):
        with lib50.working_area(["foo.py", "bar.c"]) as working_area:
            contents = os.listdir(working_area)

        self.assertEqual(set(contents), {"foo.py", "bar.c"})

    def test_include_missing_file(self):
        with self.assertRaises(FileNotFoundError):
            with lib50.working_area(["i_do_not_exist"]) as working_area:
                pass

if __name__ == '__main__':
    unittest.main()
