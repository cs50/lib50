import unittest
import os
import sys
import contextlib
import pathlib
import tempfile
import io
import re
import logging
import subprocess
import time
import termcolor
import pexpect

import lib50._api
import lib50.authentication

class TestGit(unittest.TestCase):
    def setUp(self):
        self.info_output = []

        self.old_info = lib50._api.logger.info
        self.old_debug = logging.debug

        lib50._api.logger.info = lambda msg : self.info_output.append(msg)

    def tearDown(self):
        lib50._api.logger.info = self.old_info
        lib50._api.logger.debug = self.old_debug

    def test_no_args(self):
        self.assertEqual(lib50._api.Git()("foo"), "git foo")
        self.assertEqual(self.info_output, [termcolor.colored("git foo", attrs=["bold"])])

    def test_arg(self):
        self.assertEqual(lib50._api.Git().set("bar")("foo"), "git bar foo")
        self.assertEqual(self.info_output, [termcolor.colored("git bar foo", attrs=["bold"])])

    def test_args(self):
        self.assertEqual(lib50._api.Git().set("baz")("foo"), "git baz foo")
        self.assertEqual(self.info_output, [termcolor.colored("git baz foo", attrs=["bold"])])

    def test_special_args_not_set(self):
        try:
            lib50._api.Git.work_tree = "bar"
            lib50._api.Git.git_dir = "baz"
            lib50._api.Git.cache = "qux"

            self.assertEqual(lib50._api.Git()("foo"), "git foo")
            self.assertEqual(self.info_output, [termcolor.colored("git foo", attrs=["bold"])])
        finally:
            lib50._api.Git.work_tree = ""
            lib50._api.Git.git_dir = ""
            lib50._api.Git.cache = ""

    def test_special_args(self):
        try:
            lib50._api.Git.working_area = "bar"
            lib50._api.Git.cache = "baz"

            git = lib50._api.Git().set(lib50._api.Git.working_area).set(lib50._api.Git.cache)
            self.assertEqual(git("foo"), "git bar baz foo")
            self.assertEqual(self.info_output, [termcolor.colored("git foo", attrs=["bold"])])
        finally:
            lib50._api.Git.working_area = ""
            lib50._api.Git.cache = ""

class TestSlug(unittest.TestCase):
    def test_wrong_format(self):
        with self.assertRaises(lib50._api.InvalidSlugError):
            lib50._api.Slug("/cs50/lib50/tests/bar")

        with self.assertRaises(lib50._api.InvalidSlugError):
            lib50._api.Slug("cs50/lib50/tests/bar/")

        with self.assertRaises(lib50._api.InvalidSlugError):
            lib50._api.Slug("/cs50/lib50/tests/bar/")

        with self.assertRaises(lib50._api.InvalidSlugError):
            lib50._api.Slug("cs50/problems2")

    def test_case(self):
        with self.assertRaises(lib50._api.InvalidSlugError):
            lib50._api.Slug("cs50/lib50/TESTS/bar")
        self.assertEqual(lib50._api.Slug("CS50/LiB50/tests/bar").slug, "cs50/lib50/tests/bar")

    def test_online(self):
        if os.environ.get("TRAVIS") == "true":
            self.skipTest("Cannot test online in travis.")

        slug = lib50._api.Slug("cs50/lib50/tests/bar")
        self.assertEqual(slug.slug, "cs50/lib50/tests/bar")
        self.assertEqual(slug.org, "cs50")
        self.assertEqual(slug.repo, "lib50")
        self.assertEqual(slug.branch, "tests")
        self.assertEqual(slug.problem, pathlib.Path("bar"))

    def test_wrong_slug_online(self):
        with self.assertRaises(lib50._api.InvalidSlugError):
            lib50._api.Slug("cs50/does/not/exist")

    def test_offline(self):
        try:
            old_local_path = lib50.get_local_path()
            old_wd = os.getcwd()
            temp_dir = tempfile.TemporaryDirectory()
            lib50.set_local_path(temp_dir.name)
            path = pathlib.Path(lib50.get_local_path()) / "foo" / "bar" / "baz"
            os.makedirs(path)

            os.chdir(pathlib.Path(lib50.get_local_path()) / "foo" / "bar")
            subprocess.check_output(["git", "init"])
            subprocess.check_output(["git", "config", "user.name", '"foo"'])
            subprocess.check_output(["git", "config", "user.email", '"bar@baz.com"'])
            subprocess.check_output(["git", "checkout", "-b", "main"])

            os.chdir(path)

            with open(".cs50.yaml", "w") as f:
                pass
            subprocess.check_output(["git", "add", ".cs50.yaml"])
            out = subprocess.check_output(["git", "commit", "-m", "\"qux\""])

            slug = lib50._api.Slug("foo/bar/main/baz", offline=True)
            self.assertEqual(slug.slug, "foo/bar/main/baz")
            self.assertEqual(slug.org, "foo")
            self.assertEqual(slug.repo, "bar")
            self.assertEqual(slug.branch, "main")
            self.assertEqual(slug.problem, pathlib.Path("baz"))
        finally:
            os.chdir(old_wd)
            lib50.set_local_path(old_local_path)
            temp_dir.cleanup()

    def test_wrong_slug_offline(self):
        with self.assertRaises(lib50._api.InvalidSlugError):
            lib50._api.Slug("cs50/does/not/exist", offline=True)

class TestProgressBar(unittest.TestCase):
    def test_progress(self):
        f = io.StringIO()
        with contextlib.redirect_stdout(f):
            with lib50._api.ProgressBar("foo", output_stream=sys.stdout):
                pass
        self.assertTrue("foo..." in f.getvalue())

    def test_progress_moving(self):
        f = io.StringIO()
        with contextlib.redirect_stdout(f):
            try:
                old_ticks_per_second = lib50._api.ProgressBar.TICKS_PER_SECOND
                lib50._api.ProgressBar.TICKS_PER_SECOND = 100
                with lib50._api.ProgressBar("foo", output_stream=sys.stdout):
                    time.sleep(.5)
            finally:
                lib50._api.ProgressBar.TICKS_PER_SECOND = old_ticks_per_second

        self.assertTrue("foo...." in f.getvalue())

    def test_disabled(self):
        f = io.StringIO()
        with contextlib.redirect_stdout(f):
            try:
                old_disabled = lib50._api.ProgressBar.DISABLED
                lib50._api.ProgressBar.DISABLED = True
                old_ticks_per_second = lib50._api.ProgressBar.TICKS_PER_SECOND
                lib50._api.ProgressBar.TICKS_PER_SECOND = 100
                with lib50._api.ProgressBar("foo", output_stream=sys.stdout):
                    time.sleep(.5)
            finally:
                lib50._api.ProgressBar.DISABLED = old_disabled
                lib50._api.ProgressBar.TICKS_PER_SECOND = old_ticks_per_second

        self.assertEqual("foo...\n", f.getvalue())

class TestPromptPassword(unittest.TestCase):
    @contextlib.contextmanager
    def replace_stdin(self):
        old = sys.stdin
        try:
            with tempfile.TemporaryFile() as stdin_f:
                sys.stdin = stdin_f
                sys.stdin.buffer = sys.stdin
                yield sys.stdin
        finally:
            sys.stdin = old

    @contextlib.contextmanager
    def mock_no_echo_stdin(self):
        @contextlib.contextmanager
        def mock():
            yield

        old = lib50.authentication._no_echo_stdin
        try:
            lib50.authentication._no_echo_stdin = mock
            yield mock
        finally:
            lib50._api.authentication = old

    def test_ascii(self):
        f = io.StringIO()
        with self.mock_no_echo_stdin(), self.replace_stdin(), contextlib.redirect_stdout(f):
            sys.stdin.write(bytes("foo\n".encode("utf8")))
            sys.stdin.seek(0)
            password = lib50.authentication._prompt_password()

        self.assertEqual(password, "foo")
        self.assertEqual(f.getvalue().count("*"), 3)

    def test_unicode(self):
        f = io.StringIO()
        with self.mock_no_echo_stdin(), self.replace_stdin(), contextlib.redirect_stdout(f):
            sys.stdin.write(bytes("↔♣¾€\n".encode("utf8")))
            sys.stdin.seek(0)
            password = lib50.authentication._prompt_password()

        self.assertEqual(password, "↔♣¾€")
        self.assertEqual(f.getvalue().count("*"), 4)

    def test_unicode_del(self):
        def resolve_backspaces(str):
            while True:
                temp = re.sub('.\b', '', str, count=1)
                if len(str) == len(temp):
                    return re.sub('\b+', '', temp)
                str = temp

        f = io.StringIO()
        with self.mock_no_echo_stdin(), self.replace_stdin(), contextlib.redirect_stdout(f):
            sys.stdin.write(bytes(f"↔{chr(127)}♣¾{chr(127)}€\n".encode("utf8")))
            sys.stdin.seek(0)
            password = lib50.authentication._prompt_password()

        self.assertEqual(password, "♣€")
        self.assertEqual(resolve_backspaces(f.getvalue()).count("*"), 2)


class TestGetLocalSlugs(unittest.TestCase):
    def setUp(self):
        self.old_path = lib50.get_local_path()
        self.temp_dir = tempfile.TemporaryDirectory()
        lib50.set_local_path(self.temp_dir.name)
        path = lib50.get_local_path() / "foo" / "bar" / "baz"
        os.makedirs(path)
        with open(path / ".cs50.yml", "w") as f:
            f.write("foo50: true\n")
        pexpect.run(f"git -C {path.parent.parent} init")
        pexpect.run(f'git -C {path.parent.parent} config user.name "foo"')
        pexpect.run(f'git -C {path.parent.parent} config user.email "bar@baz.com"')
        pexpect.run(f"git -C {path.parent.parent} checkout -b main")
        pexpect.run(f"git -C {path.parent.parent} add .")
        pexpect.run(f"git -C {path.parent.parent} commit -m \"message\"")

    def tearDown(self):
        lib50.set_local_path(self.old_path)
        self.temp_dir.cleanup()

    def test_one_local_slug(self):
        slugs = list(lib50.get_local_slugs("foo50"))
        self.assertEqual(len(slugs), 1)
        self.assertEqual(slugs[0], "foo/bar/main/baz")


if __name__ == '__main__':
    unittest.main()
