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
import glob
import tempfile
from copy import deepcopy
from threading import Thread
from distutils.version import StrictVersion

# Internationalization
gettext.bindtextdomain("messages", os.path.join(sys.prefix, "submit50/locale"))
gettext.textdomain("messages")
_ = gettext.gettext

def push(org, branch, tool):
    """ Push to github.com/org/repo=username/branch if tool exists """
    check_dependencies()

    tool_yaml = connect(org, branch, tool)

    with authenticate() as user:

        prepare(org, branch, user, tool_yaml)

        # TODO Submit50 special casing was here (academic honesty)

        upload(branch, user)

def connect(org, branch, tool):
    """
    Check version with submit50.io, raises Error if mismatch
    Ensure .cs50.yaml and tool key exists, raises Error otherwise
    Check that all required files as per .cs50.yaml are present
    returns tool specific portion of .cs50.yaml
    """

    with ProgressBar("Connecting"):
        problem_org, problem_repo, problem_branch, problem_dir = _parse_slug(branch)

        # get .cs50.yaml
        cs50_yaml_content = _get_content_from(problem_org, problem_repo, problem_branch, problem_dir / ".cs50.yaml")
        cs50_yaml = yaml.safe_load(cs50_yaml_content)

        # ensure tool exists
        if tool not in cs50_yaml:
            raise InvalidSlug("Invalid slug for {}, did you mean something else?".format(tool))

        # get .cs50.yaml from root if exists and merge with local
        try:
            root_cs50_yaml_content = _get_content_from(problem_org, problem_repo, problem_branch, ".cs50.yaml")
        except Error:
            pass
        else:
            root_cs50_yaml = yaml.safe_load(root_cs50_yaml_content)
            cs50_yaml = _merge_cs50_yaml(cs50_yaml, root_cs50_yaml)

        # check that all required files are present
        _check_required(cs50_yaml[tool])

        return cs50_yaml[tool]

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

def prepare(org, branch, user, tool_yaml):
    """
    Prepare git for pushing
    Check that there are no permission errors
    Add necessities to git config
    Stage files
    Stage files via lfs if necessary
    Check that atleast one file is staged
    """
    with ProgressBar("Preparing") as progress_bar, tempfile.TemporaryDirectory() as git_dir:
        # clone just .git folder
        try:
            git.Repo.clone_from(user.repo, git_dir, bare=True)
        except git.GitError:
            if user.password:
                e = Error(_("Looks like {} isn't enabled for your account yet. "
                            "Go to https://cs50.me/authorize and make sure you accept any pending invitations!".format(org)))
            else:
                e = Error(_("Looks like you have the wrong username in ~/.gitconfig or {} isn't yet enabled for your account. "
                            "Double-check ~/.gitconfig and then log into https://cs50.me/ in a browser, "
                            "click \"Authorize application\" if prompted, and re-run {} here.".format(org, org)))
            raise e


        # TODO .gitattribute stuff
        # TODO git config

        exclude = _convert_yaml_to_exclude(tool_yaml)

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
                # Note: References in .yaml become actual Python references once parsed
                # Cannot use += here!
                result[tool][key] = result[tool][key] + cs50[tool][key]
            else:
                result[tool][key] = cs50[tool][key]
    return result

def _check_required(tool_yaml):
    """ Check that all required files are present """
    try:
        tool_yaml["required"]
    except KeyError:
        return

    # TODO old submit50 had support for dirs, do we want that?

    missing = [f for f in tool_yaml["required"] if not os.path.isfile(f)]

    if missing:
        msg = "{}\n{}\n{}".format(
            _("You seem to be missing these files:"),
            "\n".join(missing),
            _("Ensure you have the required files before submitting."))
        raise Error(msg)

def _convert_yaml_to_exclude(tool_yaml):
    """
    Create a git exclude file from include + required key as per the tool's yaml entry in .cs50.yaml
        if no include key is given, all keys are included (exclude is empty)
    Includes are globbed and matched files are explicitly added to the exclude file
    """
    if "include" not in tool_yaml:
        return ""

    includes = []
    for include in tool_yaml["include"]:
        includes += glob.glob(include)

    if "required" in tool_yaml:
        includes += [req for req in tool_yaml["required"] if req not in includes]

    return "*" + "".join([f"\n!{i}" for i in includes])

if __name__ == "__main__":
    # example check50 call
    push("check50", "cs50/problems2/master/hello", "check50")
