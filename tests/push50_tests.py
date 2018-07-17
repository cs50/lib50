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
import push50
import push50.config

class TestConnect(unittest.TestCase):
    def setUp(self):
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
            included, excluded = push50.connect("cs50/problems2/foo/bar", "check50")
            self.assertEqual(excluded, set())
        self.assertTrue("Connecting..." in f.getvalue())

        f = io.StringIO()
        with contextlib.redirect_stdout(f):
            include, excluded = push50.connect("cs50/problems2/foo/bar", "submit50")
            self.assertEqual(included, {"hello.py"})
        self.assertTrue("Connecting..." in f.getvalue())

    def test_missing_problem(self):
        f = io.StringIO()
        with contextlib.redirect_stdout(f):
            with self.assertRaises(push50.InvalidSlugError):
                push50.connect("cs50/problems2/foo/i_do_not_exist", "check50")

    def test_no_tool_in_config(self):
        f = io.StringIO()
        with contextlib.redirect_stdout(f):
            with self.assertRaises(push50.InvalidSlugError):
                push50.connect("cs50/problems2/foo/bar", "i_do_not_exist")

    def test_no_config(self):
        f = io.StringIO()
        with contextlib.redirect_stdout(f):
            with self.assertRaises(push50.InvalidSlugError):
                push50.connect("cs50/problems2/foo/no_config", "check50")

class TestFiles(unittest.TestCase):
    def setUp(self):
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

        config = push50.config.load(content, "check50")

        open("foo.py", "w").close()
        open("bar.py", "w").close()

        included, excluded = push50.files(config)
        self.assertEqual(set(included), {"bar.py"})
        self.assertEqual(set(excluded), {"foo.py"})

    def test_exclude_all(self):
        content = \
            "check50:\n" \
            "  files:\n" \
            "    - !exclude \"*\"\n"

        config = push50.config.load(content, "check50")

        included, excluded = push50.files(config)
        self.assertEqual(included, set())
        self.assertEqual(excluded, set())

        open("foo.py", "w").close()

        included, excluded = push50.files(config)
        self.assertEqual(set(included), set())
        self.assertEqual(set(excluded), {"foo.py"})

    def test_include_only_one(self):
        content = \
            "check50:\n" \
            "  files:\n" \
            "    - !exclude \"*\"\n" \
            "    - !include foo.py\n"

        config = push50.config.load(content, "check50")

        open("foo.py", "w").close()
        open("bar.py", "w").close()

        included, excluded = push50.files(config)
        self.assertEqual(set(included), {"foo.py"})
        self.assertEqual(set(excluded), {"bar.py"})

    def test_include_all(self):
        config = {}

        open("foo.py", "w").close()
        open("bar.c", "w").close()

        included, excluded = push50.files(config)
        self.assertEqual(set(included), {"foo.py", "bar.c"})
        self.assertEqual(set(excluded), set())

        content = \
            "check50:\n" \
            "  files:\n" \
            "    - !include \"*\"\n"

        config = push50.config.load(content, "check50")

        included, excluded = push50.files(config)
        self.assertEqual(set(included), {"foo.py", "bar.c"})
        self.assertEqual(set(excluded), set())

    def test_required(self):
        content = \
            "check50:\n" \
            "  files:\n" \
            "    - !require foo.py\n"

        config = push50.config.load(content, "check50")

        open("foo.py", "w").close()

        included, excluded = push50.files(config)
        self.assertEqual(set(included), {"foo.py"})
        self.assertEqual(set(excluded), set())

        open("bar.c", "w").close()

        included, excluded = push50.files(config)
        self.assertEqual(set(included), {"foo.py", "bar.c"})
        self.assertEqual(set(excluded), set())

    def test_required_overwrite_exclude(self):
        content = \
            "check50:\n" \
            "  files:\n" \
            "    - !exclude \"*\"\n" \
            "    - !require foo.py\n"

        config = push50.config.load(content, "check50")

        open("foo.py", "w").close()

        included, excluded = push50.files(config)
        self.assertEqual(set(included), {"foo.py"})
        self.assertEqual(set(excluded), set())

        open("bar.c", "w").close()

        included, excluded = push50.files(config)
        self.assertEqual(set(included), {"foo.py"})
        self.assertEqual(set(excluded), {"bar.c"})

    def test_always_exclude(self):
        content = \
            "check50:\n" \
            "  files:\n" \
            "    - !include foo.py\n"

        config = push50.config.load(content, "check50")

        open("foo.py", "w").close()

        included, excluded = push50.files(config, always_exclude=["foo.py"])
        self.assertEqual(set(included), set())
        self.assertEqual(set(excluded), set())

    def test_exclude_folder_include_file(self):
        content = \
            "check50:\n" \
            "  files:\n" \
            "    - !exclude foo\n" \
            "    - !include foo/bar\n"

        config = push50.config.load(content, "check50")

        os.mkdir("foo")
        open("foo/bar", "w").close()

        included, excluded = push50.files(config)
        self.assertEqual(set(included), {"foo/bar"})
        self.assertEqual(set(excluded), set())

    def test_include_file_exclude_folder(self):
        content = \
            "check50:\n" \
            "  files:\n" \
            "    - !include foo/bar.py\n" \
            "    - !exclude foo\n"

        config = push50.config.load(content, "check50")

        os.mkdir("foo")
        open("foo/bar.py", "w").close()

        included, excluded = push50.files(config)
        self.assertEqual(set(included), set())
        self.assertEqual(set(excluded), {"foo/bar.py"})

    def test_exclude_extension_include_folder(self):
        content = \
            "check50:\n" \
            "  files:\n" \
            "    - !exclude \"*.py\"\n" \
            "    - !include foo\n"

        config = push50.config.load(content, "check50")

        os.mkdir("foo")
        open("foo/bar.py", "w").close()

        included, excluded = push50.files(config)
        self.assertEqual(set(included), {"foo/bar.py"})
        self.assertEqual(set(excluded), set())

    def test_exclude_extension_include_everything_from_folder(self):
        content = \
            "check50:\n" \
            "  files:\n" \
            "    - !exclude \"*.py\"\n" \
            "    - !include \"foo/*\"\n"

        config = push50.config.load(content, "check50")

        os.mkdir("foo")
        open("foo/bar.py", "w").close()

        included, excluded = push50.files(config)
        self.assertEqual(set(included), {"foo/bar.py"})
        self.assertEqual(set(excluded), set())

    def test_exclude_everything_include_folder(self):
        content = \
            "check50:\n" \
            "  files:\n" \
            "    - !exclude \"*\"\n" \
            "    - !include foo\n"

        config = push50.config.load(content, "check50")

        os.mkdir("foo")
        open("foo/bar.py", "w").close()

        included, excluded = push50.files(config)
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

        config = push50.config.load(content, "check50")

        included, excluded = push50.files(config)
        self.assertEqual(set(included), set())
        self.assertEqual(set(excluded), {"qux.py", "foo/bar.py"})

        content = \
            "check50:\n" \
            "  files:\n" \
            "    - !exclude \"./*.py\"\n"

        config = push50.config.load(content, "check50")

        included, excluded = push50.files(config)
        self.assertEqual(set(included), {"foo/bar.py"})
        self.assertEqual(set(excluded), {"qux.py"})

    def test_implicit_recursive_with_slash(self):
        content = \
            "check50:\n" \
            "  files:\n" \
            "    - !exclude \"*/*.py\"\n"

        config = push50.config.load(content, "check50")

        os.mkdir("foo")
        os.mkdir("foo/bar")
        open("foo/bar/baz.py", "w").close()
        open("foo/qux.py", "w").close()

        included, excluded = push50.files(config)
        self.assertEqual(set(included), {"foo/bar/baz.py"})
        self.assertEqual(set(excluded), {"foo/qux.py"})

    def test_explicit_recursive(self):
        content = \
            "check50:\n" \
            "  files:\n" \
            "    - !exclude \"foo/**/*.py\"\n"

        config = push50.config.load(content, "check50")

        os.mkdir("foo")
        os.mkdir("foo/bar")
        os.mkdir("foo/bar/baz")
        open("foo/bar/baz/qux.py", "w").close()
        open("hello.py", "w").close()

        included, excluded = push50.files(config)
        self.assertEqual(set(included), {"hello.py"})
        self.assertEqual(set(excluded), {"foo/bar/baz/qux.py"})

    def test_requires_no_exclude(self):
        content = \
            "check50:\n" \
            "  files:\n" \
            "    - !require does_not_exist.py\n"

        config = push50.config.load(content, "check50")

        with self.assertRaises(push50.MissingFilesError):
            push50.files(config)

    def test_invalid_utf8_filename(self):
        try:
            open(b"\xc3\x28", "w").close()
        except OSError:
            self.skipTest("can't create invalid utf8 filename")
        else:
            included, excluded = push50.files({})
            self.assertEqual(included, set())
            self.assertEqual(excluded, {"?("})

class TestLocal(unittest.TestCase):
    def setUp(self):
        self.working_directory = tempfile.TemporaryDirectory()
        self._wd = os.getcwd()
        os.chdir(self.working_directory.name)

    def tearDown(self):
        self.working_directory.cleanup()
        os.chdir(self._wd)

    def test_local(self):
        local_dir = push50.local("cs50/problems2/foo/bar", "check50")

        self.assertTrue(local_dir.is_dir())
        self.assertTrue((local_dir / "__init__.py").is_file())
        self.assertTrue((local_dir / ".cs50.yaml").is_file())

        local_dir = push50.local("cs50/problems2/foo/bar", "check50")

        self.assertTrue(local_dir.is_dir())
        self.assertTrue((local_dir / "__init__.py").is_file())
        self.assertTrue((local_dir / ".cs50.yaml").is_file())

        shutil.rmtree(local_dir)

        local_dir = push50.local("cs50/problems2/foo/bar", "check50")

        self.assertTrue(local_dir.is_dir())
        self.assertTrue((local_dir / "__init__.py").is_file())
        self.assertTrue((local_dir / ".cs50.yaml").is_file())

        shutil.rmtree(local_dir)


if __name__ == '__main__':
    unittest.main()
