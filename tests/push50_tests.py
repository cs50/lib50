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

class Base(unittest.TestCase):
    def setUp(self):
        self.working_directory = tempfile.TemporaryDirectory()
        os.chdir(self.working_directory.name)

        self.filename = "foo.py"
        self.write("")

    def tearDown(self):
        self.working_directory.cleanup()

    def write(self, source):
        with open(self.filename, "w") as f:
            f.write(source)

class TestGit(unittest.TestCase):
    def setUp(self):
        self.info_output = []
        self.debug_output = []

        self.old_info = logging.info
        self.old_debug = logging.debug

        logging.info = lambda msg : self.info_output.append(msg)
        logging.debug = lambda msg : self.debug_output.append(msg)

    def tearDown(self):
        logging.info = self.old_info
        logging.debug = self.old_debug

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
            push50.Git.work_tree = "bar"
            push50.Git.git_dir = "baz"
            push50.Git.cache = "qux"

            git = push50.Git(push50.Git.work_tree, push50.Git.git_dir, push50.Git.cache)
            self.assertEqual(git("foo"), "git bar baz qux foo")
            self.assertEqual(self.info_output, [termcolor.colored("git foo", attrs=["bold"])])
            self.assertTrue(self.debug_output, ["git bar baz qux foo"])
        finally:
            push50.Git.work_tree = ""
            push50.Git.git_dir = ""
            push50.Git.cache = ""

class TestSlug(unittest.TestCase):
    def test_wrong_format(self):
        with self.assertRaises(push50.InvalidSlug):
            push50.Slug("/cs50/problems2/foo/hello")

        with self.assertRaises(push50.InvalidSlug):
            push50.Slug("cs50/problems2/foo/hello/")

        with self.assertRaises(push50.InvalidSlug):
            push50.Slug("/cs50/problems2/foo/hello/")

        with self.assertRaises(push50.InvalidSlug):
            push50.Slug("cs50/problems2")

    def test_online(self):
        slug = push50.Slug("cs50/problems2/foo/hello")
        self.assertEqual(slug.slug, "cs50/problems2/foo/hello")
        self.assertEqual(slug.org, "cs50")
        self.assertEqual(slug.repo, "problems2")
        self.assertEqual(slug.branch, "foo")
        self.assertEqual(slug.problem, pathlib.Path("hello"))

    def test_wrong_slug_online(self):
        with self.assertRaises(push50.InvalidSlug):
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
        with self.assertRaises(push50.InvalidSlug):
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

if __name__ == '__main__':
    unittest.main()
