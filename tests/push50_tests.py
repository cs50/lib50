import unittest
import os
import pathlib
import shutil
import sys
import tempfile
import logging
import termcolor

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

class TestGit(Base):
    def setUp(self):
        super().setUp()
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

class TestSlug(Base):
    def test_online(self):
        slug = push50.Slug("cs50/problems2/foo/hello")
        self.assertEqual(slug.slug, "cs50/problems2/foo/hello")
        self.assertEqual(slug.org, "cs50")
        self.assertEqual(slug.repo, "problems2")
        self.assertEqual(slug.branch, "foo")
        self.assertEqual(slug.problem, pathlib.Path("hello"))

    def test_wrong_slug_online(self):
        pass

    def test_offline(self):
        pass

    def test_wrong_slug_offline(self):
        pass

if __name__ == '__main__':
    unittest.main()
