import unittest
import os
import contextlib
import pathlib
import tempfile
import io
import logging
import subprocess
import time
import termcolor
import push50.api

class TestGit(unittest.TestCase):
    def setUp(self):
        self.info_output = []
        self.debug_output = []

        self.old_info = push50.api.logger.info
        self.old_debug = logging.debug

        push50.api.logger.info = lambda msg : self.info_output.append(msg)
        push50.api.logger.debug = lambda msg : self.debug_output.append(msg)

    def tearDown(self):
        push50.api.logger.info = self.old_info
        push50.api.logger.debug = self.old_debug

    def test_no_args(self):
        self.assertEqual(push50.api.Git()("foo"), "git foo")
        self.assertEqual(self.info_output, [termcolor.colored("git foo", attrs=["bold"])])
        self.assertTrue(self.debug_output, ["git foo"])

    def test_arg(self):
        self.assertEqual(push50.api.Git().set("bar")("foo"), "git bar foo")
        self.assertEqual(self.info_output, [termcolor.colored("git bar foo", attrs=["bold"])])
        self.assertTrue(self.debug_output, ["git bar foo"])

    def test_args(self):
        self.assertEqual(push50.api.Git("bar").set("baz")("foo"), "git bar baz foo")
        self.assertEqual(self.info_output, [termcolor.colored("git bar baz foo", attrs=["bold"])])
        self.assertTrue(self.debug_output, ["git bar baz foo"])

    def test_special_args_not_set(self):
        try:
            push50.api.Git.work_tree = "bar"
            push50.api.Git.git_dir = "baz"
            push50.api.Git.cache = "qux"

            self.assertEqual(push50.api.Git()("foo"), "git foo")
            self.assertEqual(self.info_output, [termcolor.colored("git foo", attrs=["bold"])])
            self.assertTrue(self.debug_output, ["git foo"])
        finally:
            push50.api.Git.work_tree = ""
            push50.api.Git.git_dir = ""
            push50.api.Git.cache = ""

    def test_special_args(self):
        try:
            push50.api.Git.working_area = "bar"
            push50.api.Git.cache = "baz"

            git = push50.api.Git(push50.api.Git.working_area, push50.api.Git.cache)
            self.assertEqual(git("foo"), "git bar baz foo")
            self.assertEqual(self.info_output, [termcolor.colored("git foo", attrs=["bold"])])
            self.assertTrue(self.debug_output, ["git bar baz foo"])
        finally:
            push50.api.Git.working_area = ""
            push50.api.Git.cache = ""

class TestSlug(unittest.TestCase):
    def test_wrong_format(self):
        with self.assertRaises(push50.api.InvalidSlugError):
            push50.api.Slug("/cs50/problems2/foo/bar")

        with self.assertRaises(push50.api.InvalidSlugError):
            push50.api.Slug("cs50/problems2/foo/bar/")

        with self.assertRaises(push50.api.InvalidSlugError):
            push50.api.Slug("/cs50/problems2/foo/bar/")

        with self.assertRaises(push50.api.InvalidSlugError):
            push50.api.Slug("cs50/problems2")

    def test_online(self):
        slug = push50.api.Slug("cs50/problems2/foo/bar")
        self.assertEqual(slug.slug, "cs50/problems2/foo/bar")
        self.assertEqual(slug.org, "cs50")
        self.assertEqual(slug.repo, "problems2")
        self.assertEqual(slug.branch, "foo")
        self.assertEqual(slug.problem, pathlib.Path("bar"))

    def test_wrong_slug_online(self):
        with self.assertRaises(push50.api.InvalidSlugError):
            push50.api.Slug("cs50/does/not/exist")

    def test_offline(self):
        try:
            old_local_path = push50.api.LOCAL_PATH
            old_wd = os.getcwd()

            push50.api.LOCAL_PATH = tempfile.TemporaryDirectory().name
            path = pathlib.Path(push50.api.LOCAL_PATH) / "foo" / "bar" / "baz"
            os.makedirs(path)

            os.chdir(pathlib.Path(push50.api.LOCAL_PATH) / "foo" / "bar")
            subprocess.check_output(["git", "init"])

            os.chdir(path)

            with open(".cs50.yaml", "w") as f:
                pass
            subprocess.check_output(["git", "add", ".cs50.yaml"])
            out = subprocess.check_output(["git", "commit", "-m", "qux"])

            slug = push50.api.Slug("foo/bar/master/baz", offline=True)
            self.assertEqual(slug.slug, "foo/bar/master/baz")
            self.assertEqual(slug.org, "foo")
            self.assertEqual(slug.repo, "bar")
            self.assertEqual(slug.branch, "master")
            self.assertEqual(slug.problem, pathlib.Path("baz"))
        finally:
            push50.api.LOCAL_PATH = old_local_path
            os.chdir(old_wd)

    def test_wrong_slug_offline(self):
        with self.assertRaises(push50.api.InvalidSlugError):
            push50.api.Slug("cs50/does/not/exist", offline=True)

class TestProgressBar(unittest.TestCase):
    def test_progress(self):
        f = io.StringIO()
        with contextlib.redirect_stdout(f):
            with push50.api.ProgressBar("foo"):
                pass
        self.assertTrue("foo..." in f.getvalue())

    def test_progress_moving(self):
        f = io.StringIO()
        with contextlib.redirect_stdout(f):
            try:
                old_ticks_per_second = push50.api.ProgressBar.TICKS_PER_SECOND
                push50.api.ProgressBar.TICKS_PER_SECOND = 100
                with push50.api.ProgressBar("foo"):
                    time.sleep(.5)
            finally:
                push50.api.ProgressBar.TICKS_PER_SECOND = old_ticks_per_second

        self.assertTrue("foo...." in f.getvalue())

    def test_disabled(self):
        f = io.StringIO()
        with contextlib.redirect_stdout(f):
            try:
                old_disabled = push50.api.ProgressBar.DISABLED
                push50.api.ProgressBar.DISABLED = True
                old_ticks_per_second = push50.api.ProgressBar.TICKS_PER_SECOND
                push50.api.ProgressBar.TICKS_PER_SECOND = 100
                with push50.api.ProgressBar("foo"):
                    time.sleep(.5)
            finally:
                push50.api.ProgressBar.DISABLED = old_disabled
                push50.api.ProgressBar.TICKS_PER_SECOND = old_ticks_per_second

        self.assertEqual("foo...\n", f.getvalue())

if __name__ == '__main__':
    unittest.main()
