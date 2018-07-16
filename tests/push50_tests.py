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

class TestGit(unittest.TestCase):
    def setUp(self):
        self.info_output = []
        self.debug_output = []

        self.old_info = push50.logger.info
        self.old_debug = logging.debug

        push50.logger.info = lambda msg : self.info_output.append(msg)
        push50.logger.debug = lambda msg : self.debug_output.append(msg)

    def tearDown(self):
        push50.logger.info = self.old_info
        push50.logger.debug = self.old_debug

    def test_no_args(self):
        self.assertEqual(push50.Git()("foo"), "git foo")
        self.assertEqual(self.info_output, [termcolor.colored("git foo", attrs=["bold"])])
        self.assertTrue(self.debug_output, ["git foo"])

    def test_arg(self):
        self.assertEqual(push50.Git().set("bar")("foo"), "git bar foo")
        self.assertEqual(self.info_output, [termcolor.colored("git bar foo", attrs=["bold"])])
        self.assertTrue(self.debug_output, ["git bar foo"])

    def test_args(self):
        self.assertEqual(push50.Git("bar").set("baz")("foo"), "git bar baz foo")
        self.assertEqual(self.info_output, [termcolor.colored("git bar baz foo", attrs=["bold"])])
        self.assertTrue(self.debug_output, ["git bar baz foo"])

    def test_special_args_not_set(self):
        try:
            push50.Git.work_tree = "bar"
            push50.Git.git_dir = "baz"
            push50.Git.cache = "qux"

            self.assertEqual(push50.Git()("foo"), "git foo")
            self.assertEqual(self.info_output, [termcolor.colored("git foo", attrs=["bold"])])
            self.assertTrue(self.debug_output, ["git foo"])
        finally:
            push50.Git.work_tree = ""
            push50.Git.git_dir = ""
            push50.Git.cache = ""

    def test_special_args(self):
        try:
            push50.Git.working_area = "bar"
            push50.Git.cache = "baz"

            git = push50.Git(push50.Git.working_area, push50.Git.cache)
            self.assertEqual(git("foo"), "git bar baz foo")
            self.assertEqual(self.info_output, [termcolor.colored("git foo", attrs=["bold"])])
            self.assertTrue(self.debug_output, ["git bar baz foo"])
        finally:
            push50.Git.working_area = ""
            push50.Git.cache = ""

class TestSlug(unittest.TestCase):
    def test_wrong_format(self):
        with self.assertRaises(push50.InvalidSlugError):
            push50.Slug("/cs50/problems2/foo/bar")

        with self.assertRaises(push50.InvalidSlugError):
            push50.Slug("cs50/problems2/foo/bar/")

        with self.assertRaises(push50.InvalidSlugError):
            push50.Slug("/cs50/problems2/foo/bar/")

        with self.assertRaises(push50.InvalidSlugError):
            push50.Slug("cs50/problems2")

    def test_online(self):
        slug = push50.Slug("cs50/problems2/foo/bar")
        self.assertEqual(slug.slug, "cs50/problems2/foo/bar")
        self.assertEqual(slug.org, "cs50")
        self.assertEqual(slug.repo, "problems2")
        self.assertEqual(slug.branch, "foo")
        self.assertEqual(slug.problem, pathlib.Path("bar"))

    def test_wrong_slug_online(self):
        with self.assertRaises(push50.InvalidSlugError):
            push50.Slug("cs50/does/not/exist")

    def test_offline(self):
        try:
            old_local_path = push50.LOCAL_PATH
            old_wd = os.getcwd()

            push50.LOCAL_PATH = tempfile.TemporaryDirectory().name
            path = pathlib.Path(push50.LOCAL_PATH) / "foo" / "bar" / "baz"
            os.makedirs(path)

            os.chdir(pathlib.Path(push50.LOCAL_PATH) / "foo" / "bar")
            subprocess.check_output(["git", "init"])

            os.chdir(path)

            with open(".cs50.yaml", "w") as f:
                pass
            subprocess.check_output(["git", "add", ".cs50.yaml"])
            out = subprocess.check_output(["git", "commit", "-m", "qux"])

            slug = push50.Slug("foo/bar/master/baz", offline=True)
            self.assertEqual(slug.slug, "foo/bar/master/baz")
            self.assertEqual(slug.org, "foo")
            self.assertEqual(slug.repo, "bar")
            self.assertEqual(slug.branch, "master")
            self.assertEqual(slug.problem, pathlib.Path("baz"))
        finally:
            push50.LOCAL_PATH = old_local_path
            os.chdir(old_wd)

    def test_wrong_slug_offline(self):
        with self.assertRaises(push50.InvalidSlugError):
            push50.Slug("cs50/does/not/exist", offline=True)

class TestProgressBar(unittest.TestCase):
    def test_progress(self):
        f = io.StringIO()
        with contextlib.redirect_stdout(f):
            with push50.ProgressBar("foo"):
                pass
        self.assertTrue("foo..." in f.getvalue())

    def test_progress_moving(self):
        f = io.StringIO()
        with contextlib.redirect_stdout(f):
            try:
                old_ticks_per_second = push50.ProgressBar.TICKS_PER_SECOND
                push50.ProgressBar.TICKS_PER_SECOND = 100
                with push50.ProgressBar("foo"):
                    time.sleep(.5)
            finally:
                push50.ProgressBar.TICKS_PER_SECOND = old_ticks_per_second

        self.assertTrue("foo...." in f.getvalue())

    def test_disabled(self):
        f = io.StringIO()
        with contextlib.redirect_stdout(f):
            try:
                old_disabled = push50.ProgressBar.DISABLED
                push50.ProgressBar.DISABLED = True
                old_ticks_per_second = push50.ProgressBar.TICKS_PER_SECOND
                push50.ProgressBar.TICKS_PER_SECOND = 100
                with push50.ProgressBar("foo"):
                    time.sleep(.5)
            finally:
                push50.ProgressBar.DISABLED = old_disabled
                push50.ProgressBar.TICKS_PER_SECOND = old_ticks_per_second

        self.assertEqual("foo...\n", f.getvalue())

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
        config = {
            "exclude" : ["foo.py"]
        }

        open("foo.py", "w").close()
        open("bar.py", "w").close()

        included, excluded = push50.files(config)
        self.assertEqual(set(included), {"bar.py"})
        self.assertEqual(set(excluded), {"foo.py"})

    def test_exclude_all(self):
        config = {
            "exclude" : ["*"]
        }

        included, excluded = push50.files(config)
        self.assertEqual(included, set())
        self.assertEqual(excluded, set())

        open("foo.py", "w").close()

        included, excluded = push50.files(config)
        self.assertEqual(set(included), set())
        self.assertEqual(set(excluded), {"foo.py"})

    def test_include_only_one(self):
        config = {
            "exclude" : ["*", "!foo.py"]
        }

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

        config = {
            "exclude" : ["!*"]
        }

        included, excluded = push50.files(config)
        self.assertEqual(set(included), {"foo.py", "bar.c"})
        self.assertEqual(set(excluded), set())

    def test_required(self):
        config = {
            "required" : ["foo.py"]
        }

        open("foo.py", "w").close()

        included, excluded = push50.files(config)
        self.assertEqual(set(included), {"foo.py"})
        self.assertEqual(set(excluded), set())

        open("bar.c", "w").close()

        included, excluded = push50.files(config)
        self.assertEqual(set(included), {"foo.py", "bar.c"})
        self.assertEqual(set(excluded), set())

    def test_required_overwrite_exclude(self):
        config = {
            "exclude" : ["*"],
            "required" : ["foo.py"]
        }

        open("foo.py", "w").close()

        included, excluded = push50.files(config)
        self.assertEqual(set(included), {"foo.py"})
        self.assertEqual(set(excluded), set())

        open("bar.c", "w").close()

        included, excluded = push50.files(config)
        self.assertEqual(set(included), {"foo.py"})
        self.assertEqual(set(excluded), {"bar.c"})

    def test_always_exclude(self):
        config = {
            "exclude" : ["!foo.py"]
        }

        open("foo.py", "w").close()

        included, excluded = push50.files(config, always_exclude=["foo.py"])
        self.assertEqual(set(included), set())
        self.assertEqual(set(excluded), set())

    def test_exclude_folder_include_file(self):
        config = {
            "exclude" : ["foo", "!foo/bar"]
        }

        os.mkdir("foo")
        open("foo/bar", "w").close()

        included, excluded = push50.files(config)
        self.assertEqual(set(included), {"foo/bar"})
        self.assertEqual(set(excluded), set())

    def test_include_file_exclude_folder(self):
        config = {
            "exclude" : ["!foo/bar.py", "foo"]
        }

        os.mkdir("foo")
        open("foo/bar.py", "w").close()

        included, excluded = push50.files(config)
        self.assertEqual(set(included), set())
        self.assertEqual(set(excluded), {"foo/bar.py"})

    def test_exclude_extension_include_folder(self):
        config = {
            "exclude" : ["*.py", "!foo"]
        }

        os.mkdir("foo")
        open("foo/bar.py", "w").close()

        included, excluded = push50.files(config)
        self.assertEqual(set(included), {"foo/bar.py"})
        self.assertEqual(set(excluded), set())

    def test_exclude_extension_include_everything_from_folder(self):
        config = {
            "exclude" : ["*.py", "!foo/*"]
        }

        os.mkdir("foo")
        open("foo/bar.py", "w").close()

        included, excluded = push50.files(config)
        self.assertEqual(set(included), {"foo/bar.py"})
        self.assertEqual(set(excluded), set())

    def test_exclude_everything_include_folder(self):
        config = {
            "exclude" : ["*", "!foo"]
        }

        os.mkdir("foo")
        open("foo/bar.py", "w").close()

        included, excluded = push50.files(config)
        self.assertEqual(set(included), {"foo/bar.py"})
        self.assertEqual(set(excluded), set())

    def test_implicit_recursive(self):
        os.mkdir("foo")
        open("foo/bar.py", "w").close()
        open("qux.py", "w").close()

        config = {
            "exclude" : ["*.py"]
        }

        included, excluded = push50.files(config)
        self.assertEqual(set(included), set())
        self.assertEqual(set(excluded), {"qux.py", "foo/bar.py"})

        config = {
            "exclude" : ["./*.py"]
        }

        included, excluded = push50.files(config)
        self.assertEqual(set(included), {"foo/bar.py"})
        self.assertEqual(set(excluded), {"qux.py"})

    def test_implicit_recursive_with_slash(self):
        config = {
            "exclude" : ["*/*.py"]
        }

        os.mkdir("foo")
        os.mkdir("foo/bar")
        open("foo/bar/baz.py", "w").close()
        open("foo/qux.py", "w").close()

        included, excluded = push50.files(config)
        self.assertEqual(set(included), {"foo/bar/baz.py"})
        self.assertEqual(set(excluded), {"foo/qux.py"})

    def test_explicit_recursive(self):
        config = {
            "exclude" : ["foo/**/*.py"]
        }

        os.mkdir("foo")
        os.mkdir("foo/bar")
        os.mkdir("foo/bar/baz")
        open("foo/bar/baz/qux.py", "w").close()
        open("hello.py", "w").close()

        included, excluded = push50.files(config)
        self.assertEqual(set(included), {"hello.py"})
        self.assertEqual(set(excluded), {"foo/bar/baz/qux.py"})

    def test_requires_no_exclude(self):
        config = {
            "required": ["does_not_exist.py"]
        }

        with self.assertRaises(push50.MissingFilesError):
            push50.files(config)

    def test_invalid_utf8_filename(self):
        open(b"\xc3\x28", "w").close()
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
