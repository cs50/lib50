import contextlib
import fnmatch
import glob
import logging
import os
from pathlib import Path
import pkg_resources
import re
import shutil
import shlex
import subprocess
import sys
import tempfile
import threading
import time
import functools

import jellyfish
import pexpect
import requests
import termcolor

from . import _, get_local_path
from ._errors import *
from .authentication import authenticate, logout, run_authenticated
from . import config as lib50_config

__all__ = ["push", "local", "working_area", "files", "connect",
           "prepare", "authenticate", "upload", "logout", "ProgressBar",
           "fetch_config", "get_local_slugs", "check_github_status", "Slug", "cd"]

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())

DEFAULT_PUSH_ORG = "me50"
AUTH_URL = "https://submit.cs50.io"


DEFAULT_FILE_LIMIT = 10000


def push(tool, slug, config_loader, repo=None, data=None, prompt=lambda question, included, excluded: True, file_limit=DEFAULT_FILE_LIMIT):
    """
    Pushes to Github in name of a tool.
    What should be pushed is configured by the tool and its configuration in the .cs50.yml file identified by the slug.
    By default, this function pushes to https://github.com/org=me50/repo=<username>/branch=<slug>.

    ``lib50.push`` executes the workflow: ``lib50.connect``, ``lib50.authenticate``, ``lib50.prepare`` and ``lib50.upload``.

    :param tool: name of the tool that initialized the push
    :type tool: str
    :param slug: the slug identifying a .cs50.yml config file in a GitHub repo. This slug is also the branch in the student's repo to which this will push.
    :type slug: str
    :param config_loader: a config loader for the tool that is able to parse the .cs50.yml config file for the tool.
    :type config_loader: lib50.config.Loader
    :param repo: an alternative repo to push to, otherwise the default is used: github.com/me50/<github_login>
    :type repo: str, optional
    :param data: key value pairs that end up in the commit message. This can be used to communicate data with a backend.
    :type data: dict of strings, optional
    :param prompt: a prompt shown just before the push. In case this prompt returns false, the push is aborted. This lambda function has access to an honesty prompt configured in .cs50,yml, and all files that will be included and excluded in the push.
    :type prompt: lambda str, list, list => bool, optional
    :param file_limit: maximum number of files to be matched by any globbing pattern.
    :type file_limit: int
    :return: GitHub username and the commit hash
    :type: tuple(str, str)

    Example usage::

        from lib50 import push
        import submit50

        name, hash = push("submit50", "cs50/problems/2019/x/hello", submit50.CONFIG_LOADER)
        print(name)
        print(hash)

    """
    if data is None:
        data = {}

    language = os.environ.get("LANGUAGE")
    if language:
        data.setdefault("lang", language)

    slug = Slug.normalize_case(slug)

    check_dependencies()

    # Connect to GitHub and parse the config files
    remote, (honesty, included, excluded) = connect(slug, config_loader, file_limit=DEFAULT_FILE_LIMIT)

    # Authenticate the user with GitHub, and prepare the submission
    with authenticate(remote["org"], repo=repo) as user, prepare(tool, slug, user, included):

        # Show any prompt if specified
        if prompt(honesty, included, excluded):
            username, commit_hash = upload(slug, user, tool, data)
            format_dict = {"username": username, "slug": slug, "commit_hash": commit_hash}
            message = remote["message"].format(results=remote["results"].format(**format_dict), **format_dict)
            return username, commit_hash, message
        else:
            raise Error(_("No files were submitted."))


def local(slug, offline=False, remove_origin=False, github_token=None):
    """
    Create/update local copy of the GitHub repo indentified by slug.
    The local copy is shallow and single branch, it contains just the last commit on the branch identified by the slug.

    :param slug: the slug identifying a GitHub repo.
    :type slug: str
    :param offline: a flag that indicates whether the user is offline. If so, then the local copy is only checked, but not updated.
    :type offline: bool, optional
    :param remove_origin: a flag, that when set to True, will remove origin as a remote of the git repo.
    :type remove_origin: bool, optional
    :param github_token: a GitHub authentication token used to verify the slug, only needed if the slug identifies a private repo.
    :type github_token: str, optional
    :return: path to local copy
    :type: pathlib.Path

    Example usage::

        from lib50 import local

        path = local("cs50/problems/2019/x/hello")
        print(list(path.glob("**/*")))

    """

    # Parse slug
    slug = Slug(slug, offline=offline, github_token=github_token)

    local_path = get_local_path() / slug.org / slug.repo

    git = Git().set("-C {path}", path=str(local_path))
    if not local_path.exists():
        run(Git()("init {path}", path=str(local_path)))
        run(git(f"remote add origin {slug.origin}"))

    if not offline:
        # Get latest version of checks
        run(git("fetch origin --depth 1 {branch}", branch=slug.branch))

    # Tolerate checkout failure (e.g., when origin doesn't exist)
    try:
        run(git("checkout -f -B {branch} origin/{branch}", branch=slug.branch))
    except Error:
        pass

    # Ensure that local copy of the repo is identical to remote copy
    run(git("reset --hard HEAD"))

    if remove_origin:
        run(git(f"remote remove origin"))

    problem_path = (local_path / slug.problem).absolute()

    if not problem_path.exists():
        raise InvalidSlugError(_("{} does not exist at {}/{}").format(slug.problem, slug.org, slug.repo))

    return problem_path


@contextlib.contextmanager
def working_area(files, name=""):
    """
    A contextmanager that copies all files to a temporary directory (the working area)

    :param files: all files to copy to the temporary directory
    :type files: list of string(s) or pathlib.Path(s)
    :param name: name of the temporary directory
    :type name: str, optional
    :return: path to the working area
    :type: pathlib.Path

    Example usage::

        from lib50 import working_area

        with working_area(["foo.c", "bar.py"], name="baz") as area:
            print(list(area.glob("**/*")))

    """
    with tempfile.TemporaryDirectory() as dir:
        dir = Path(Path(dir) / name)
        dir.mkdir(exist_ok=True)

        for f in files:
            dest = (dir / f).absolute()
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(f, dest)
        yield dir


@contextlib.contextmanager
def cd(dest):
    """
    A contextmanager for temporarily changing directory.

    :param dest: the path to the directory
    :type dest: str or pathlib.Path
    :return: dest unchanged
    :type: str or pathlib.Path

    Example usage::

        from lib50 import cd
        import os

        with cd("foo") as current_dir:
            print(os.getcwd())

    """
    origin = os.getcwd()
    try:
        os.chdir(dest)
        yield dest
    finally:
        os.chdir(origin)


def files(patterns,
          require_tags=("require",),
          include_tags=("include",),
          exclude_tags=("exclude",),
          root=".",
          limit=DEFAULT_FILE_LIMIT):
    """
    Based on a list of patterns (``lib50.config.TaggedValue``) determine which files should be included and excluded.
    Any pattern tagged with a tag:

    * from ``include_tags`` will be included
    * from ``require_tags`` can only be a file, that will then be included. ``MissingFilesError`` is raised if missing.
    * from ``exclude_tags`` will be excluded

    :param patterns: patterns that are processed in order, to determine which files should be included and excluded.
    :type patterns: list of lib50.config.TaggedValue
    :param require_tags: tags that mark a file as required and through that included
    :type require_tags: list of strings, optional
    :param include_tags: tags that mark a pattern as included
    :type include_tags:  list of strings, optional
    :param exclude_tags: tags that mark a pattern as excluded
    :type exclude_tags: list of strings, optional
    :param root: the root directory from which to look for files. Defaults to the current directory.
    :type root: str or pathlib.Path, optional
    :param limit: Maximum number of files that can be globbed.
    :type limit: int
    :return: all included files and all excluded files
    :type: tuple(set of strings, set of strings)

    Example usage::

        from lib50 import files
        from lib50.config import TaggedValue

        open("foo.py", "w").close()
        open("bar.c", "w").close()
        open("baz.h", "w").close()

        patterns = [TaggedValue("*", "exclude"),
                    TaggedValue("*.c", "include"),
                    TaggedValue("baz.h", "require")]

        print(files(patterns)) # prints ({'bar.c', 'baz.h'}, {'foo.py'})

    """
    require_tags = list(require_tags)
    include_tags = list(include_tags)
    exclude_tags = list(exclude_tags)

    # Ensure tags do not start with !
    for tags in [require_tags, include_tags, exclude_tags]:
        for i, tag in enumerate(tags):
            tags[i] = tag[1:] if tag.startswith("!") else tag

    with cd(root):
        # Include everything but hidden paths by default
        included = _glob("*", limit=limit)
        excluded = set()

        if patterns:
            missing_files = []

            # For each pattern
            for pattern in patterns:
                if not _is_relative_to(Path(pattern.value).expanduser().resolve(), Path.cwd()):
                    raise Error(_("Cannot include/exclude paths outside the current directory, but such a path ({}) was specified.")
                                .format(pattern.value))

                # Include all files that are tagged with !require
                if pattern.tag in require_tags:
                    file = str(Path(pattern.value))
                    if not Path(file).exists():
                        missing_files.append(file)
                    else:
                        try:
                            excluded.remove(file)
                        except KeyError:
                            pass
                        else:
                            included.add(file)
                # Include all files that are tagged with !include
                elif pattern.tag in include_tags:
                    new_included = _glob(pattern.value, limit=limit)
                    excluded -= new_included
                    included.update(new_included)
                # Exclude all files that are tagged with !exclude
                elif pattern.tag in exclude_tags:
                    new_excluded = _glob(pattern.value, limit=limit)
                    included -= new_excluded
                    excluded.update(new_excluded)

            if missing_files:
                raise MissingFilesError(missing_files)

    # Exclude any files that are not valid utf8
    invalid = set()
    for file in included:
        try:
            file.encode("utf8")
        except UnicodeEncodeError:
            excluded.add(file.encode("utf8", "replace").decode())
            invalid.add(file)
    included -= invalid

    return included, excluded


def connect(slug, config_loader, file_limit=DEFAULT_FILE_LIMIT):
    """
    Connects to a GitHub repo indentified by slug.
    Then parses the ``.cs50.yml`` config file with the ``config_loader``.
    If not all required files are present, per the ``files`` tag in ``.cs50.yml``, an ``Error`` is raised.

    :param slug: the slug identifying a GitHub repo.
    :type slug: str
    :param config_loader: a config loader that is able to parse the .cs50.yml config file for a tool.
    :type config_loader: lib50.config.Loader
    :param file_limit: The maximum number of files that are allowed to be included.
    :type file_limit: int
    :return: the remote configuration (org, message, callback, results), and the input for a prompt (honesty question, included files, excluded files)
    :type: tuple(dict, tuple(str, set, set))
    :raises lib50.InvalidSlugError: if the slug is invalid for the tool
    :raises lib50.Error: if no files are staged. For instance the slug expects .c files, but there are only .py files present.

    Example usage::

        from lib50 import connect
        import submit50

        open("hello.c", "w").close()

        remote, (honesty, included, excluded) = connect("cs50/problems/2019/x/hello", submit50.CONFIG_LOADER)

    """
    with ProgressBar(_("Connecting")):
        # Get the config from GitHub at slug
        config_yaml = fetch_config(slug)

        # Load config file
        try:
            config = config_loader.load(config_yaml)
        except MissingToolError:
            raise InvalidSlugError(_("Invalid slug for {}. Did you mean something else?").format(config_loader.tool))

        # If config of tool is just a truthy value, config should be empty
        if not isinstance(config, dict):
            config = {}

        # By default send check50/style50 results back to submit.cs50.io
        remote = {
            "org": DEFAULT_PUSH_ORG,
            "message": _("Go to {results} to see your results."),
            "callback": "https://submit.cs50.io/hooks/results",
            "results": "https://submit.cs50.io/users/{username}/{slug}"
        }

        remote.update(config.get("remote", {}))
        honesty = config.get("honesty", True)

        # Figure out which files to include and exclude
        included, excluded = files(config.get("files"), limit=file_limit)

        # Check that at least 1 file is staged
        if not included:
            raise Error(_("No files in this directory are expected by {}.".format(slug)))

        return remote, (honesty, included, excluded)


@contextlib.contextmanager
def prepare(tool, branch, user, included):
    """
    A contextmanager that prepares git for pushing:

    * Check that there are no permission errors
    * Add necessities to git config
    * Stage files
    * Stage files via lfs if necessary
    * Check that atleast one file is staged

    :param tool: name of the tool that started the push
    :type tool: str
    :param branch: git branch to switch to
    :type branch: str
    :param user: the user who has access to the repo, and will ultimately author a commit
    :type user: lib50.User
    :param included: a list of files that are to be staged in git
    :type included: list of string(s) or pathlib.Path(s)
    :return: None
    :type: None

    Example usage::

        from lib50 import authenticate, prepare, upload

        with authenticate("me50") as user:
            tool = "submit50"
            branch = "cs50/problems/2019/x/hello"
            with prepare(tool, branch, user, ["hello.c"]):
                upload(branch, user, tool, {})

    """
    with working_area(included) as area:
        with ProgressBar(_("Verifying")):
            Git.working_area = f"-C {shlex.quote(str(area))}"
            git = Git().set(Git.working_area)

            # Clone just .git folder
            try:
                clone_command = f"clone --bare --single-branch {user.repo} .git"
                try:
                    run_authenticated(user, git.set(Git.cache)(f"{clone_command} --branch {branch}"))
                except Error:
                    run_authenticated(user, git.set(Git.cache)(clone_command))
            except Error:
                msg = _("Make sure your username and/or personal access token are valid and {} is enabled for your account. To enable {}, ").format(tool, tool)
                if user.org != DEFAULT_PUSH_ORG:
                    msg += _("please contact your instructor.")
                else:
                    msg += _("please go to {} in your web browser and try again.").format(AUTH_URL)

                msg += _((" For instructions on how to set up a personal access token, please visit https://cs50.ly/github"))

                raise Error(msg)

        with ProgressBar(_("Preparing")) as progress_bar:
            run(git("config --bool core.bare false"))
            run(git("config --path core.worktree {area}", area=str(area)))

            try:
                run(git("checkout --force {branch} .gitattributes", branch=branch))
            except Error:
                pass

            # Set user name/email in repo config
            run(git("config user.email {email}", email=user.email))
            run(git("config user.name {name}", name=user.name))

            # Switch to branch without checkout
            run(git("symbolic-ref HEAD {ref}", ref=f"refs/heads/{branch}"))

            # Git add all included files
            run(git(f"add -f {' '.join(shlex.quote(f) for f in included)}"))

            # Remove gitattributes from included
            if Path(".gitattributes").exists() and ".gitattributes" in included:
                included.remove(".gitattributes")

            # Add any oversized files through git-lfs
            _lfs_add(included, git)

            progress_bar.stop()
            yield


def upload(branch, user, tool, data):
    """
    Commit + push to a branch

    :param branch: git branch to commit and push to
    :type branch: str
    :param user: authenticated user who can push to the repo and branch
    :type user: lib50.User
    :param tool: name of the tool that started the push
    :type tool: str
    :param data: key value pairs that end up in the commit message. This can be used to communicate data with a backend.
    :type data: dict of strings
    :return: username and commit hash
    :type: tuple(str, str)

    Example usage::

        from lib50 import authenticate, prepare, upload

        with authenticate("me50") as user:
            tool = "submit50"
            branch = "cs50/problems/2019/x/hello"
            with prepare(tool, branch, user, ["hello.c"]):
                upload(branch, user, tool, {tool:True})

    """
    with ProgressBar(_("Uploading")):
        commit_message = _("automated commit by {}").format(tool)

        data_str = " ".join(f"[{key}={val}]" for key, val in data.items())

        commit_message = f"{commit_message} {data_str}"

        # Commit + push
        git = Git().set(Git.working_area)
        run(git("commit -m {msg} --allow-empty", msg=commit_message))
        run_authenticated(user, git.set(Git.cache)("push origin {branch}", branch=branch))
        commit_hash = run(git("rev-parse HEAD"))
        return user.name, commit_hash


def fetch_config(slug):
    """
    Fetch the config file at slug from GitHub.

    :param slug: a slug identifying a location on GitHub to fetch the config from.
    :type slug: str
    :return: the config in the form of unparsed json
    :type: str
    :raises lib50.InvalidSlugError: if there is no config file at slug.

    Example usage::

        from lib50 import fetch_config

        config = fetch_config("cs50/problems/2019/x/hello")
        print(config)

    """
    # Parse slug
    slug = Slug(slug)

    # Get config file (.cs50.yaml)
    try:
        yaml_content = get_content(slug.org, slug.repo, slug.branch, slug.problem / ".cs50.yaml")
    except InvalidSlugError:
        yaml_content = None

    # Get config file (.cs50.yml)
    try:
        yml_content = get_content(slug.org, slug.repo, slug.branch, slug.problem / ".cs50.yml")
    except InvalidSlugError:
        yml_content = None

    # If neither exists, error
    if not yml_content and not yaml_content:
        # Check if GitHub outage may be the source of the issue
        check_github_status()

        # Otherwise raise an InvalidSlugError
        raise InvalidSlugError(_("Invalid slug: {}. Did you mean something else?").format(slug))

    # If both exists, error
    if yml_content and yaml_content:
        raise InvalidSlugError(_("Invalid slug: {}. Multiple configurations (both .yaml and .yml) found.").format(slug))

    return yml_content or yaml_content


def get_local_slugs(tool, similar_to=""):
    """
    Get all slugs for tool of which lib50 has a local copy.
    If similar_to is given, ranks and sorts local slugs by similarity to similar_to.

    :param tool: tool for which to get the local slugs
    :type tool: str
    :param similar_to: ranks and sorts local slugs by similarity to this slug
    :type similar_to: str, optional
    :return: list of slugs
    :type: list of strings

    Example usage::

        from lib50 import get_local_slugs

        slugs = get_local_slugs("check50", similar_to="cs50/problems/2019/x/hllo")
        print(slugs)

    """
    # Extract org and repo from slug to limit search
    similar_to = similar_to.strip("/")
    parts = Path(similar_to).parts
    entered_org = parts[0] if len(parts) >= 1 else ""
    entered_repo = parts[1] if len(parts) >= 2 else ""

    # Find path of local repo's
    local_path = get_local_path()
    local_repo = local_path / entered_org / entered_repo

    if not local_repo.exists():
        local_repo = local_path

    # Find all local config files within local_path
    config_paths = []
    for root, dirs, files in os.walk(local_repo):
        try:
            config_paths.append(lib50_config.get_config_filepath(root))
        except Error:
            pass

    # Filter out all local config files that do not contain tool
    config_loader = lib50_config.Loader(tool)
    valid_paths = []
    for config_path in config_paths:
        with open(config_path) as f:
            if config_loader.load(f.read(), validate=False):
                valid_paths.append(config_path.relative_to(local_path))

    # Find branch for every repo
    branch_map = {}
    for path in valid_paths:
        org, repo = path.parts[0:2]
        if (org, repo) not in branch_map:
            git = Git().set("-C {path}", path=str(local_path / path.parent))
            branch = run(git("rev-parse --abbrev-ref HEAD"))
            branch_map[(org, repo)] = branch

    # Reconstruct slugs for each config file
    slugs = []
    for path in valid_paths:
        org, repo = path.parts[0:2]
        branch = branch_map[(org, repo)]
        problem = "/".join(path.parts[2:-1])
        slugs.append("/".join((org, repo, branch, problem)))

    return _rank_similar_slugs(similar_to, slugs) if similar_to else slugs


def _rank_similar_slugs(target_slug, other_slugs):
    """
    Rank other_slugs by their similarity to target_slug.
    Returns a list of other_slugs in order (most similar -> least similar).
    """
    if len(Path(target_slug).parts) >= 2:
        other_slugs_filtered = [slug for slug in other_slugs if Path(slug).parts[0:2] == Path(target_slug).parts[0:2]]
        if other_slugs_filtered:
            other_slugs = other_slugs_filtered

    scores = {}
    for other_slug in other_slugs:
        scores[other_slug] = jellyfish.jaro_winkler(target_slug, other_slug)

    return sorted(scores, key=lambda k: scores[k], reverse=True)


def check_dependencies():
    """
    Check that dependencies are installed:
    - require git 2.7+, so that credential-cache--daemon ignores SIGHUP
        https://github.com/git/git/blob/v2.7.0/credential-cache--daemon.c
    """

    # Check that git is installed
    if not shutil.which("git"):
        raise Error(_("You don't have git. Install git, then re-run!"))

    # Check that git --version > 2.7
    version = subprocess.check_output(["git", "--version"]).decode("utf-8")
    matches = re.search(r"^git version (\d+\.\d+\.\d+).*$", version)
    if not matches or pkg_resources.parse_version(matches.group(1)) < pkg_resources.parse_version("2.7.0"):
        raise Error(_("You have an old version of git. Install version 2.7 or later, then re-run!"))


class Git:
    """
    A stateful helper class for formatting git commands.

    To avoid confusion, and because these are not directly relevant to users,
    the class variables ``cache`` and ``working_area`` are excluded from logs.

    Example usage::

        command = Git().set("-C {folder}", folder="foo")("git clone {repo}", repo="foo")
        print(command)
    """
    cache = ""
    working_area = ""

    def __init__(self):
        self._args = []

    def set(self, git_arg, **format_args):
        """git = Git().set("-C {folder}", folder="foo")"""
        format_args = {name: shlex.quote(arg) for name, arg in format_args.items()}
        git = Git()
        git._args = self._args[:]
        git._args.append(git_arg.format(**format_args))
        return git

    def __call__(self, command, **format_args):
        """Git()("git clone {repo}", repo="foo")"""
        git = self.set(command, **format_args)

        git_command = f"git {' '.join(git._args)}"

        # Format to show in git info
        logged_command = f"git {' '.join(arg for arg in git._args if arg not in [str(git.cache), str(Git.working_area)])}"

        # Log pretty command in info
        logger.info(termcolor.colored(logged_command, attrs=["bold"]))

        return git_command


class Slug:
    """
    A CS50 slug that uniquely identifies a location on GitHub.

    A slug is formatted as follows: <org>/<repo>/<branch>/<problem>
    Both the branch and the problem can have an arbitrary number of slashes.
    ``lib50.Slug`` performs validation on the slug, by querrying GitHub,
    pulling in all branches, and then by finding a branch and problem that matches the slug.

    :ivar str org: the GitHub organization
    :ivar str repo: the GitHub repo
    :ivar str branch: the branch in the repo
    :ivar str problem: path to the problem, the directory containing ``.cs50.yml``
    :ivar str slug: string representation of the slug
    :ivar bool offline: flag signalling whether the user is offline. If set to True, the slug is parsed locally.
    :ivar str origin: GitHub url for org/repo including authentication.

    Example usage::

        from lib50._api import Slug

        slug = Slug("cs50/problems/2019/x/hello")
        print(slug.org)
        print(slug.repo)
        print(slug.branch)
        print(slug.problem)

    """

    def __init__(self, slug, offline=False, github_token=None):
        """Parse <org>/<repo>/<branch>/<problem_dir> from slug."""
        self.slug = self.normalize_case(slug)
        self.offline = offline

        # Assert begin/end of slug are correct
        self._check_endings()

        # Find third "/" in identifier
        idx = self.slug.find("/", self.slug.find("/") + 1)
        if idx == -1:
            raise InvalidSlugError(_("Invalid slug"))

        # Split slug in <org>/<repo>/<remainder>
        remainder = self.slug[idx + 1:]
        self.org, self.repo = self.slug.split("/")[:2]

        credentials = f"{github_token}:x-oauth-basic@" if github_token else ""
        self.origin = f"https://{credentials}github.com/{self.org}/{self.repo}"

        # Gather all branches
        try:
            branches = self._get_branches()
        except TimeoutError:
            if not offline:
                raise ConnectionError("Could not connect to GitHub, it seems you are offline.")
            branches = []
        except ConnectionError:
            raise
        except Error:
            branches = []

        # Find a matching branch
        for branch in branches:
            if remainder.startswith(f"{branch}"):
                self.branch = branch
                self.problem = Path(remainder[len(branch) + 1:])
                break
        else:
            raise InvalidSlugError(_("Invalid slug: {}").format(self.slug))

    def _check_endings(self):
        """Check begin/end of slug, raises Error if malformed."""
        if self.slug.startswith("/") and self.slug.endswith("/"):
            raise InvalidSlugError(
                _("Invalid slug. Did you mean {}, without the leading and trailing slashes?").format(self.slug.strip("/")))
        elif self.slug.startswith("/"):
            raise InvalidSlugError(
                _("Invalid slug. Did you mean {}, without the leading slash?").format(self.slug.strip("/")))
        elif self.slug.endswith("/"):
            raise InvalidSlugError(
                _("Invalid slug. Did you mean {}, without the trailing slash?").format(self.slug.strip("/")))

    def _get_branches(self):
        """Get branches from org/repo."""
        if self.offline:
            local_path = get_local_path() / self.org / self.repo
            output = run(f"git -C {shlex.quote(str(local_path))} show-ref --heads").split("\n")
        else:
            cmd = f"git ls-remote --heads {self.origin}"
            try:
                with spawn(cmd, timeout=3) as child:
                    output = child.read().strip().split("\r\n")
            except pexpect.TIMEOUT:
                if "Username for" in child.buffer:
                    return []
                else:
                    raise TimeoutError(3)
            except Error:
                if "Could not resolve host" in child.before + child.buffer:
                    raise ConnectionError
                raise

        # Parse get_refs output for the actual branch names
        return (line.split()[1].replace("refs/heads/", "") for line in output)

    @staticmethod
    def normalize_case(slug):
        """Normalize the case of a slug in string form"""
        parts = slug.split("/")
        if len(parts) < 3:
            raise InvalidSlugError(_("Invalid slug"))
        parts[0] = parts[0].lower()
        parts[1] = parts[1].lower()
        return "/".join(parts)

    def __str__(self):
        return self.slug


class ProgressBar:
    """
    A contextmanager that shows a progress bar starting with message.

    Example usage::

        from lib50 import ProgressBar
        import time

        with ProgressBar("uploading") as bar:
            time.sleep(5)
            bar.stop()
            time.sleep(5)

    """
    DISABLED = False
    TICKS_PER_SECOND = 2

    def __init__(self, message, output_stream=None):
        """
        :param message: the message of the progress bar, what the user is waiting on
        :type message: str
        :param output_stream: a stream to write the progress bar to
        :type output_stream: a stream or file-like object
        """

        if output_stream is None:
            output_stream = sys.stderr

        self._message = message
        self._progressing = False
        self._thread = None
        self._print = functools.partial(print, file=output_stream)

    def stop(self):
        """Stop the progress bar."""
        if self._progressing:
            self._progressing = False
            self._thread.join()

    def __enter__(self):
        def progress_runner():
            self._print(f"{self._message}...", end="", flush=True)
            while self._progressing:
                self._print(".", end="", flush=True)
                time.sleep(1 / ProgressBar.TICKS_PER_SECOND if ProgressBar.TICKS_PER_SECOND else 0)
            self._print()

        if not ProgressBar.DISABLED:
            self._progressing = True
            self._thread = threading.Thread(target=progress_runner)
            self._thread.start()
        else:
            self._print(f"{self._message}...")

        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()


class _StreamToLogger:
    """Send all that enters the stream to log-function."""

    def __init__(self, log):
        self._log = log

    def write(self, message):
        message = message.strip()
        if message:
            self._log(message)

    def flush(self):
        pass


@contextlib.contextmanager
def spawn(command, quiet=False, timeout=None):
    """Run (spawn) a command with `pexpect.spawn`"""
    # Spawn command
    child = pexpect.spawn(
        command,
        encoding="utf-8",
        env=dict(os.environ),
        timeout=timeout)

    try:
        if not quiet:
            # Log command output to logger
            child.logfile_read = _StreamToLogger(logger.debug)
        yield child
    except BaseException:
        child.close()
        raise
    else:
        if child.isalive():
            try:
                child.expect(pexpect.EOF, timeout=timeout)
            except pexpect.TIMEOUT:
                raise Error()
        child.close(force=True)
        if child.signalstatus is None and child.exitstatus != 0:
            logger.debug("{} exited with {}".format(command, child.exitstatus))
            raise Error()


def run(command, quiet=False, timeout=None):
    """Run a command, returns command output."""
    try:
        with spawn(command, quiet, timeout) as child:
            command_output = child.read().strip().replace("\r\n", "\n")
    except pexpect.TIMEOUT:
        logger.info(f"command {command} timed out")
        raise TimeoutError(timeout)

    return command_output


def _glob(pattern, skip_dirs=False, limit=DEFAULT_FILE_LIMIT):
    """
    Glob pattern, expand directories, return iterator over matching files.
    Throws ``lib50.TooManyFilesError`` if more than ``limit`` files are globbed.
    """
    # Implicit recursive iff no / in pattern and starts with *
    files = glob.iglob(f"**/{pattern}" if "/" not in pattern and pattern.startswith("*")
                       else pattern, recursive=True)

    all_files = set()

    def add_file(f):
        fname = str(Path(f))
        all_files.add(fname)
        if len(all_files) > limit:
            raise TooManyFilesError(limit)

    # Expand dirs
    for file in files:
        if os.path.isdir(file) and not skip_dirs:
            for f in _glob(f"{file}/**/*", skip_dirs=True):
                if not os.path.isdir(f):
                    add_file(f)
        else:
            add_file(file)

    return all_files


def _match_files(universe, pattern):
    """From a universe of files, get just those files that match the pattern."""
    # Implicit recursive iff no / in pattern and starts with *
    if "/" not in pattern and pattern.startswith("*"):
        pattern = f"**/{pattern}"
    pattern = re.compile(fnmatch.translate(pattern))
    return set(file for file in universe if pattern.match(file))


def get_content(org, repo, branch, filepath):
    """Get all content from org/repo/branch/filepath at GitHub."""
    url = "https://github.com/{}/{}/raw/{}/{}".format(org, repo, branch, filepath)
    r = requests.get(url)
    if not r.ok:
        if r.status_code == 404:
            raise InvalidSlugError(_("Invalid slug. Did you mean to submit something else?"))
        else:
            # Check if GitHub outage may be the source of the issue
            check_github_status()

            # Otherwise raise a ConnectionError
            raise ConnectionError(_("Could not connect to GitHub. Do make sure you are connected to the internet."))
    return r.content


def check_github_status():
    """
    Pings the githubstatus API. Raises a ConnectionError if the Git Operations and/or
    API requests components show an increase in errors.

    :return: None
    :type: None
    :raises lib50.ConnectionError: if the Git Operations and/or API requests components show an increase in errors.
    """
    # https://www.githubstatus.com/api
    status_result = requests.get("https://kctbh9vrtdwd.statuspage.io/api/v2/components.json")

    # If status check failed
    if not status_result.ok:
        raise ConnectionError(_("Could not connect to GitHub. Do make sure you are connected to the internet."))

    # Get the components lib50 uses
    components = status_result.json()["components"]
    relevant_components = [c for c in components if c["name"] in ("Git Operations", "API Requests")]

    # If there is an indication of errors on GitHub's side
    for component in components:
        if component["status"] != "operational":
            raise ConnectionError(
                _("Could not connect to GitHub. "
                  "It looks like GitHub is having some issues with {}. "
                  "Do check on https://www.githubstatus.com and try again later.").format(component['name']))


def _lfs_add(files, git):
    """
    Add any oversized files with lfs.
    Throws error if a file is bigger than 2GB or git-lfs is not installed.
    """
    # Check for large files > 100 MB (and huge files > 2 GB)
    # https://help.github.com/articles/conditions-for-large-files/
    # https://help.github.com/articles/about-git-large-file-storage/
    larges, huges = [], []
    for file in files:
        size = os.path.getsize(file)
        if size > (100 * 1024 * 1024):
            larges.append(file)
        elif size > (2 * 1024 * 1024 * 1024):
            huges.append(file)

    # Raise Error if a file is >2GB
    if huges:
        raise Error(_("These files are too large to be submitted:\n{}\n"
                      "Remove these files from your directory "
                      "and then re-run!").format("\n".join(huges)))

    # Add large files (>100MB) with git-lfs
    if larges:
        # Raise Error if git-lfs not installed
        if not shutil.which("git-lfs"):
            raise Error(_("These files are too large to be submitted:\n{}\n"
                          "Install git-lfs (or remove these files from your directory) "
                          "and then re-run!").format("\n".join(larges)))

        # Install git-lfs for this repo
        run(git("lfs install --local"))

        # For pre-push hook
        run(git("config credential.helper cache"))

        # Rm previously added file, have lfs track file, add file again
        for large in larges:
            run(git("rm --cached {large}", large=large))
            run(git("lfs track {large}", large=large))
            run(git("add {large}", large=large))
        run(git("add --force .gitattributes"))


def _is_relative_to(path, *others):
    """The is_relative_to method for Paths is Python 3.9+ so we implement it here."""
    try:
        path.relative_to(*others)
        return True
    except ValueError:
        return False

