import os
import sys
import time
import requests
import subprocess
import re
import pathlib
import contextlib
import shutil
import gettext
import yaml
import git
from copy import deepcopy
from threading import Thread
from distutils.version import StrictVersion

# Internationalization
gettext.bindtextdomain("messages", os.path.join(sys.prefix, "submit50/locale"))
gettext.textdomain("messages")
_ = gettext.gettext

def push(org, branch, sentinel = None):
    """ Push to org/user/branch if sentinel exists """
    check_dependencies()

    push50_yaml = connect(org, branch, sentinel)

    with authenticate() as user:

        prepare(org, branch, user, push50_yaml)

        # TODO Submit50 special casing was here (academic honesty)

        upload(branch, user)

def connect(org, branch, sentinel = None):
    """
    Check version with submit50.io, raises Error if mismatch
    Ensure .cs50.yaml and sentinel exist, raises Error if does not exist
    Check that all required files as per .cs50.yaml are present
    returns .cs50.yaml
    """

    with ProgressBar("Connecting"):
        problem_org, problem_repo, problem_branch, problem_dir = _parse_slug(branch)

        # get .cs50.yaml
        cs50_yaml_content = _get_content_from(problem_org, problem_repo, problem_branch, problem_dir / ".cs50.yaml")
        cs50_yaml = yaml.safe_load(cs50_yaml_content)

        # ensure sentinel exists
        if sentinel and sentinel not in cs50_yaml:
            raise Error("Invalid slug for {}, did you mean something else?".format(sentinel))

        # get .cs50.yaml from root if exists and merge with local
        try:
            root_cs50_yaml_content = _get_content_from(problem_org, problem_repo, problem_branch, ".cs50.yaml")
        except Error:
            pass
        else:
            root_cs50_yaml = yaml.safe_load(root_cs50_yaml_content)
            cs50_yaml = _merge_cs50_yaml(cs50_yaml, root_cs50_yaml)

        # check that all required files are present
        _check_required(cs50_yaml)

        return cs50_yaml

@contextlib.contextmanager
def authenticate():
    """
    Authenticate with GitHub via SSH if possible
    Otherwise authenticate via HTTPS
    returns: an authenticated User
    """
    with ProgressBar("Authenticating"):
        pass
    yield User("username", "password", "email@email.com", "user_repo")
    # TODO destroy socket

def prepare(org, branch, user, push50_yaml):
    """
    Prepare git for pushing
    Check that there are no permission errors
    Add necessities to git config
    Stage files
    Stage files via lfs if necessary
    Check that atleast one file is staged
    """
    with ProgressBar("Preparing"):
        # TODO clone bare
            # TODO check for any permission errors: CS50.me / wrong username
        # TODO .gitattribute stuff
        # TODO git config
        # TODO add files to staging area
        # TODO git lfs
        # TODO check that at least 1 file is staged
        pass

def upload(branch, password):
    """ Commit + push to branch """
    with ProgressBar("Uploading"):
        # TODO decide on commit name
        # TODO commit + push
        pass

def check_dependencies():
    """
    Check that dependencies are installed:
    - require git 2.7+, so that credential-cache--daemon ignores SIGHUP
        https://github.com/git/git/blob/v2.7.0/credential-cache--daemon.c
    """

    # check that git is installed
    if not shutil.which("git"):
        raise Error(_("You don't have git. Install git, then re-run!"))

    # check that git --version > 2.7
    version = subprocess.check_output(["git", "--version"]).decode("utf-8")
    matches = re.search(r"^git version (\d+\.\d+\.\d+).*$", version)
    if not matches or StrictVersion(matches.group(1)) < StrictVersion("2.7.0"):
        raise Error(_("You have an old version of git. Install version 2.7 or later, then re-run!"))

class Error(Exception):
    pass

class InvalidSlug(Error):
    pass

class User:
    def __init__(self, name, password, email, repo):
        self.name = name
        self.password = password
        self.email = email
        self.repo = repo

class ProgressBar:
    """ Show a progress bar starting with message """
    def __init__(self, message):
        self._message = message
        self._progressing = True
        self._paused = False
        self._thread = None

    def pause(self):
        """Pause the progress bar"""
        self._paused = True

    def unpause(self):
        """Unpause the progress bar"""
        self._paused = False

    def __enter__(self):
        def progress_runner():
            sys.stdout.write(self._message + "...")
            sys.stdout.flush()
            while self._progressing:
                if not self._paused:
                    sys.stdout.write(".")
                    sys.stdout.flush()
                time.sleep(0.5)
            print()

        self._thread = Thread(target=progress_runner)
        self._thread.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._progressing = False
        self._thread.join()

def _parse_slug(slug, offline=False):
    """ parse <org>/<repo>/<branch>/<problem_dir> from slug """
    if slug.startswith("/") and slug.endswith("/"):
        raise InvalidSlug(_("Invalid slug. Did you mean {}, without the leading and trailing slashes?".format(slug.strip("/"))))
    elif slug.startswith("/"):
        raise InvalidSlug(_("Invalid slug. Did you mean {}, without the leading slash?".format(slug.strip("/"))))
    elif slug.endswith("/"):
        raise InvalidSlug(_("Invalid slug. Did you mean {}, without the trailing slash?".format(slug.strip("/"))))

    # Find third "/" in identifier
    idx = slug.find("/", slug.find("/") + 1)
    if idx == -1:
        raise InvalidSlug(slug)

    remainder = slug[idx+1:]
    org = slug.split("/")[0]
    repo = slug.split("/")[1]

    def parse_branch(offline):
        try:
            if not offline:
                try:
                    return parse_branch(offline=True)
                except InvalidSlug:
                    branches = (line.split("\t")[1].replace("refs/heads/", "")
                                for line in git.Git().ls_remote(f"https://github.com/{org}/{repo}", heads=True).split("\n"))
            else:
                branches = map(str, git.Repo(f"~/.local/share/push50/{org}/{repo}").branches)
        except git.GitError:
            raise InvalidSlug(slug)

        for branch in branches:
            if remainder.startswith(f"{branch}/"):
                return branch, remainder[len(branch)+1:]
        else:
            raise InvalidSlug(slug)

    branch, problem = parse_branch(offline)

    return org, repo, branch, pathlib.Path(problem)

def _get_content_from(org, repo, branch, filepath):
    """ Get all content from org/repo/branch/filepath at GitHub """
    url = "https://github.com/{}/{}/raw/{}/{}".format(org, repo, branch, filepath)
    r = requests.get(url)
    if not r.ok:
        raise Error(_("Invalid slug. Did you mean to submit something else?"))
    return r.content

def _merge_cs50_yaml(cs50, root_cs50):
    """ Merge .cs50.yaml with .cs50.yaml from root of repo """
    result = deepcopy(root_cs50)

    for tool in cs50:
        if tool not in root_cs50:
            result[tool] = cs50[tool]
            continue

        for key in cs50[tool]:
            if key in root_cs50[tool] and isinstance(root_cs50[tool][key], list):
                result[tool][key] += cs50[tool][key]
            else:
                result[tool][key] = cs50[tool][key]

    return result

def _check_required(cs50_yaml):
    """ Check that all required files are present """
    try:
        cs50_yaml["check50"]["required"]
    except KeyError:
        return

    # TODO old submit50 had support for dirs, do we want that?

    missing = [f for f in cs50_yaml["check50"]["required"] if not os.path.isfile(f)]

    if missing:
        msg = "{}\n{}\n{}".format(
            _("You seem to be missing these files:"),
            "\n".join(missing),
            _("Ensure you have the required files before submitting."))
        raise Error(msg)

if __name__ == "__main__":
    # example check50 call
    push("check50", "cs50/problems2/master/hello", sentinel = "check50")
