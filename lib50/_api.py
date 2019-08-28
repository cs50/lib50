import collections
import contextlib
import copy
import datetime
import fnmatch
import functools
import gettext
import glob
import itertools
import logging
import os
import platform
import signal
from pathlib import Path
import pkg_resources
import re
import shutil
import subprocess
import sys
import stat
import tempfile
import threading
import time

import attr
import jellyfish
import pexpect
import requests
import termcolor
import yaml

from . import _, get_local_path
from ._errors import *
from . import config as lib50_config

ON_WINDOWS = os.name == "nt"

if ON_WINDOWS:
    import msvcrt
    from winpty import PtyProcess
    from pexpect import popen_spawn
    quote = lambda text: text
else:
    import termios
    import tty
    quote = __import__("shlex").quote

__all__ = ["push", "local", "working_area", "files", "connect",
           "prepare", "authenticate", "upload", "logout", "ProgressBar",
           "fetch_config", "get_local_slugs", "check_github_status", "Slug", "cd"]

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())

_CREDENTIAL_SOCKET = Path("~/.git-credential-cache/lib50").expanduser()
DEFAULT_PUSH_ORG = "me50"
PASSWORD = ""

def push(tool, slug, config_loader, repo=None, data=None, prompt=lambda included, excluded: True):
    """
    Push to github.com/org/repo=username/slug if tool exists.
    Returns username, commit hash
    """

    if data is None:
        data = {}

    language = os.environ.get("LANGUAGE")
    if language:
        data.setdefault("lang", language)

    slug = Slug.normalize_case(slug)

    check_dependencies()

    # Connect to GitHub and parse the config files
    org, (included, excluded), message = connect(slug, config_loader)

    # Authenticate the user with GitHub, and prepare the submission
    with authenticate(org, repo=repo) as user, prepare(tool, slug, user, included):

        # Show any prompt if specified
        if prompt(included, excluded):
            username, commit_hash = upload(slug, user, tool, data)
            return username, commit_hash, message.format(username=username, slug=slug, commit_hash=commit_hash)
        else:
            raise Error(_("No files were submitted."))


def local(slug, offline=False):
    """
    Create/update local copy of github.com/org/repo/branch.
    Returns path to local copy
    """

    # Parse slug
    slug = Slug(slug, offline=offline)

    local_path = get_local_path() / slug.org / slug.repo

    git = Git().set("-C {path}", path=str(local_path))
    if not local_path.exists():
        _run(Git()("init {path}", path=str(local_path)))
        _run(git(f"remote add origin https://github.com/{slug.org}/{slug.repo}"))

    if not offline:
        # Get latest version of checks
        _run(git("fetch origin {branch}", branch=slug.branch))

    # Ensure that local copy of the repo is identical to remote copy
    _run(git("checkout -f -B {branch} origin/{branch}", branch=slug.branch))
    _run(git("reset --hard HEAD"))

    problem_path = (local_path / slug.problem).absolute()

    if not problem_path.exists():
        raise InvalidSlugError(_("{} does not exist at {}/{}").format(slug.problem, slug.org, slug.repo))

    return problem_path


@contextlib.contextmanager
def working_area(files, name=""):
    """
    Copy all files to a temporary directory (the working area)
    Optionally names the working area name
    Returns path to the working area
    """
    with tempfile.TemporaryDirectory() as dir:
        dir = Path(Path(dir) / name).absolute()
        dir.mkdir(exist_ok=True)

        for f in files:
            dest = (dir / f).absolute()
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(f, dest)
        yield dir

        # Ensure we have permission to cleanup tempdir on Windows
        if ON_WINDOWS:
            for root, dirs, files in os.walk(str(dir)):
                for fname in files:
                    full_path = os.path.join(root, fname)
                    os.chmod(full_path, stat.S_IWRITE)


@contextlib.contextmanager
def cd(dest):
    """ Temporarily cd into a directory"""
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
          root="."):
    """
    Takes a list of lib50._config.TaggedValue returns which files should be included and excluded from `root`.
    Any pattern tagged with a tag
        from include_tags will be included
        from require_tags can only be a file, that will then be included. MissingFilesError is raised if missing
        from exclude_tags will be excluded
    Any pattern in always_exclude will always be excluded.
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
        included = _glob("*")
        excluded = set()

        if patterns:
            missing_files = []

            # For each pattern
            for pattern in patterns:
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
                    new_included = _glob(pattern.value)
                    excluded -= new_included
                    included.update(new_included)
                # Exclude all files that are tagged with !exclude
                elif pattern.tag in exclude_tags:
                    new_excluded = _glob(pattern.value)
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


def connect(slug, config_loader):
    """
    Ensure .cs50.yaml and tool key exists, raises Error otherwise
    Check that all required files as per .cs50.yaml are present
    Returns org, and a tuple of included and excluded files
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
            "message": "Go to https://submit.cs50.io/users/{username}/{slug} to see your results.",
            "callback": "https://submit.cs50.io/hooks/results"
        }

        remote.update(config.get("remote", {}))

        # Figure out which files to include and exclude
        included, excluded = files(config.get("files"))

        # Check that at least 1 file is staged
        if not included:
            raise Error(_("No files in this directory are expected for submission."))

        return remote["org"], (included, excluded), remote["message"]


@contextlib.contextmanager
def authenticate(org, repo=None):
    """
    Authenticate with GitHub via SSH if possible
    Otherwise authenticate via HTTPS
    Returns an authenticated User
    """
    with ProgressBar(_("Authenticating")) as progress_bar:
        progress_bar.stop()
        user = _authenticate_ssh(org, repo=repo)
        if user is None:
            # SSH auth failed, fallback to HTTPS
            with _authenticate_https(org, repo=repo) as user:
                yield user
        else:
            yield user


@contextlib.contextmanager
def prepare(tool, branch, user, included):
    """
    Prepare git for pushing
    Check that there are no permission errors
    Add necessities to git config
    Stage files
    Stage files via lfs if necessary
    Check that atleast one file is staged
    """
    with ProgressBar(_("Preparing")) as progress_bar, working_area(included) as area:
        Git.working_area = f"-C {quote(str(area))}"
        git = Git().set(Git.working_area)
        # Clone just .git folder
        try:
            _run(git.set(Git.cache)("clone --bare {repo} .git", repo=user.repo), password=PASSWORD)
        except Error:
            msg = _("Looks like {} isn't enabled for your account yet. ").format(tool)
            if user.org != DEFAULT_PUSH_ORG:
                msg += _("Please contact your instructor about this issue.")
            else:
                msg += _("Please go to https://submit.cs50.io in your web browser and try again.")

            raise Error(msg)

        _run(git("config --bool core.bare false"))
        _run(git("config --path core.worktree {area}", area=str(area)))

        try:
            _run(git("checkout --force {branch} .gitattributes", branch=branch))
        except Error:
            pass

        # Set user name/email in repo config
        _run(git("config user.email {email}", email=user.email))
        _run(git("config user.name {name}", name=user.name))

        # Switch to branch without checkout
        _run(git("symbolic-ref HEAD {ref}", ref=f"refs/heads/{branch}"))

        # Git add all included files
        _run(git(f"add -f {' '.join(quote(f) for f in included)}"))

        # Remove gitattributes from included
        if Path(".gitattributes").exists() and ".gitattributes" in included:
            included.remove(".gitattributes")

        # Add any oversized files through git-lfs
        _lfs_add(included, git)

        progress_bar.stop()
        yield


def upload(branch, user, tool, data):
    """
    Commit + push to branch
    Returns username, commit hash
    """

    with ProgressBar(_("Uploading")):
        commit_message = _("automated commit by {}").format(tool)

        data_str = " ".join(itertools.chain([""], (f"[{key}={val}]" for key, val in data.items())))

        commit_message = f"{commit_message}{data_str}"

        # Commit + push
        git = Git().set(Git.working_area)

        if ON_WINDOWS:
            commit_message = commit_message.replace(" ", "_")

        _run(git("commit -m {msg} --allow-empty", msg=commit_message))
        _run(git.set(Git.cache)("push origin {branch}", branch=branch), password=PASSWORD)
        commit_hash = _run(git("rev-parse HEAD"))
        return user.name, commit_hash


def fetch_config(slug):
    """
    Fetch the config file at slug from GitHub.
    Returns the unparsed json as a string.
    Raises InvalidSlugError if there is no config file at slug.
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
    Get all slugs for tool of lib50 has a local copy.
    If similar_to is given, ranks local slugs by similarity to similar_to.
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
            branch = _run(git("rev-parse --abbrev-ref HEAD"))
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


def logout():
    _run(f"git credential-cache --socket {_CREDENTIAL_SOCKET} exit")


@attr.s(slots=True)
class User:
    name = attr.ib()
    repo = attr.ib()
    org = attr.ib()
    email = attr.ib(default=attr.Factory(lambda self: f"{self.name}@users.noreply.github.com",
                                         takes_self=True),
                    init=False)


class Git:
    cache = ""
    working_area = ""

    def __init__(self):
        self._args = []

    def set(self, git_arg, **format_args):
        """git = Git().set("-C {folder}", folder="foo")"""
        format_args = {name: quote(arg) for name, arg in format_args.items()}
        git = Git()
        git._args = self._args[:]
        git._args.append(git_arg.format(**format_args))
        return git

    def __call__(self, command, **format_args):
        """Git()("git clone {repo}", repo="foo")"""
        git = self.set(command, **format_args)

        git_command = f"git {' '.join(git._args)}"
        git_command = re.sub(' +', ' ', git_command)

        # Format to show in git info
        logged_command = git_command
        for opt in [Git.cache, Git.working_area]:
            logged_command = logged_command.replace(str(opt), "")
        logged_command = re.sub(' +', ' ', logged_command)

        # Log pretty command in info
        logger.info(termcolor.colored(logged_command, attrs=["bold"]))

        return git_command


class Slug:
    def __init__(self, slug, offline=False):
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

        # Gather all branches
        try:
            branches = self._get_branches()
        except TimeoutError:
            if not offline:
                raise ConnectionError("Could not connect to GitHub, it seems you are offline.")
            branches = []
        except Error:
            branches = []

        # Find a matching branch
        for branch in branches:
            if remainder.startswith(f"{branch}"):
                self.branch = branch
                self.problem = Path(remainder[len(branch) + 1:])
                break
        else:
            raise InvalidSlugError(_("Invalid slug: {}".format(self.slug)))

    def _check_endings(self):
        """Check begin/end of slug, raises Error if malformed."""
        if self.slug.startswith("/") and self.slug.endswith("/"):
            raise InvalidSlugError(
                _("Invalid slug. Did you mean {}, without the leading and trailing slashes?".format(self.slug.strip("/"))))
        elif self.slug.startswith("/"):
            raise InvalidSlugError(
                _("Invalid slug. Did you mean {}, without the leading slash?".format(self.slug.strip("/"))))
        elif self.slug.endswith("/"):
            raise InvalidSlugError(
                _("Invalid slug. Did you mean {}, without the trailing slash?".format(self.slug.strip("/"))))

    def _get_branches(self):
        """Get branches from org/repo."""
        if self.offline:
            local_path = get_local_path() / self.org / self.repo
            output = _run(f"git -C {quote(str(local_path))} show-ref --heads").split("\n")
        else:
            cmd = f"git ls-remote --heads https://github.com/{self.org}/{self.repo}"
            try:
                with _spawn(cmd, timeout=3) as child:
                    if ON_WINDOWS:
                        # Ignore first line
                        child.readline()
                        output = _escape_ansi(child.read()).split("\r\n")
                    else:
                        output = child.read().strip().split("\r\n")
            except pexpect.TIMEOUT:
                if "Username for" in child.buffer:
                    return []
                else:
                    raise TimeoutError(3)

        # Parse get_refs output for the actual branch names
        return (line.split()[1].replace("refs/heads/", "") for line in output)

    @staticmethod
    def normalize_case(slug):
        parts = slug.split("/")
        if len(parts) < 3:
            raise InvalidSlugError(_("Invalid slug"))
        parts[0] = parts[0].lower()
        parts[1] = parts[1].lower()
        return "/".join(parts)


    def __str__(self):
        return self.slug


class ProgressBar:
    """Show a progress bar starting with message."""
    DISABLED = False
    TICKS_PER_SECOND = 2

    def __init__(self, message, output_stream=None):

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


if ON_WINDOWS:
    @contextlib.contextmanager
    def _spawn(command, quiet=False, timeout=None, password=None):
        # Spawn command
        child = PtyProcess.spawn(
            command,
            env=dict(os.environ)
        )

        # Mimic pexpect process api
        child.sendline = lambda line: child.write(line + "\n")

        try:
            # Preemptively feed user's password
            if child.isalive() and password is not None:
                child.sendline(password)
            yield child
        except BaseException:
            del child
            raise
        else:
            # Wait for process to finish gracefully
            timeout = timeout if timeout else 30
            start = time.time()
            while child.isalive() and time.time() < start + timeout:
                time.sleep(.1)

            # Get the exitstatus and force quit
            exitstatus = child.exitstatus
            del child

            # Log any failed commands
            if exitstatus != 0:
                logger.debug("{} exited with {}".format(command, exitstatus))

else:
    @contextlib.contextmanager
    def _spawn(command, quiet=False, timeout=None, password=None):
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
            # Wait for process to finish gracefully
            if child.isalive():
                try:
                    child.expect(pexpect.EOF, timeout=timeout)
                except pexpect.TIMEOUT:
                    raise Error()

            # Get the exitstatus and force quit
            child.close(force=True)
            exitstatus = child.exitstatus

            # Log any failed commands
            if child.signalstatus is None and exitstatus != 0:
                logger.debug("{} exited with {}".format(command, child.exitstatus))


def _run(command, quiet=False, timeout=None, password=None):
    """Run a command, returns command output."""
    try:
        with _spawn(command, quiet, timeout, password) as child:
            if ON_WINDOWS:
                child.read()
            try:
                command_output = _escape_ansi(child.read().replace("\r\n", "\n")).strip()
            except EOFError:
                command_output = ""
    except pexpect.TIMEOUT:
        logger.info(f"command {command} timed out")
        raise TimeoutError(timeout)

    return command_output


def _glob(pattern, skip_dirs=False):
    """Glob pattern, expand directories, return all files that matched."""
    # Implicit recursive iff no / in pattern and starts with *
    if "/" not in pattern and pattern.startswith("*"):
        files = glob.glob(f"**/{pattern}", recursive=True)
    else:
        files = glob.glob(pattern, recursive=True)

    # Expand dirs
    all_files = set()
    for file in files:
        if os.path.isdir(file) and not skip_dirs:
            all_files.update(set(f for f in _glob(f"{file}/**/*", skip_dirs=True) if not os.path.isdir(f)))
        else:
            all_files.add(file)

    # Normalize all files
    return {str(Path(f)) for f in all_files}


def _match_files(universe, pattern):
    # Implicit recursive iff no / in pattern and starts with *
    if "/" not in pattern and pattern.startswith("*"):
        pattern = f"**/{pattern}"
    pattern = re.compile(fnmatch.translate(pattern))
    return set(file for file in universe if pattern.match(file))


def get_content(org, repo, branch, filepath):
    """Get all content from org/repo/branch/filepath at GitHub."""
    url = "https://github.com/{}/{}/raw/{}/{}".format(org, repo, branch, "/".join(Path(filepath).parts))
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
    Pings the githubstatus API. Raises an Error if the Git Operations and/or
    API requests components show an increase in errors.
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
            raise ConnectionError(_(f"Could not connect to GitHub. It looks like GitHub is having some issues with {component['name']}. Do check on https://www.githubstatus.com and try again later."))


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
                      "and then re-run!").format("\n".join(huges), org))

    # Add large files (>100MB) with git-lfs
    if larges:
        # Raise Error if git-lfs not installed
        if not shutil.which("git-lfs"):
            raise Error(_("These files are too large to be submitted:\n{}\n"
                          "Install git-lfs (or remove these files from your directory) "
                          "and then re-run!").format("\n".join(larges)))

        # Install git-lfs for this repo
        _run(git("lfs install --local"))

        # For pre-push hook
        _run(git("config credential.helper cache"))

        # Rm previously added file, have lfs track file, add file again
        for large in larges:
            _run(git("rm --cached {large}", large=large))
            _run(git("lfs track {large}", large=large))
            _run(git("add {large}", large=large))
        _run(git("add --force .gitattributes"))


def _authenticate_ssh(org, repo=None):
    """Try authenticating via ssh, if succesful yields a User, otherwise raises Error."""
    if ON_WINDOWS:
        # Ensure 64-bit Windows can find 32-bit Python under windows
        system32 = os.path.join(os.environ['SystemRoot'], 'SysNative' if platform.architecture()[0] == '32bit' else 'System32')
        ssh_path = os.path.join(system32, 'OpenSSH\\ssh.exe')
        pexpect_spawn = popen_spawn.PopenSpawn
    else:
        pexpect_spawn = pexpect.spawn
        ssh_path = "ssh"

    # -oBatchMode=yes prevents password prompt on OpenSSH
    # https://serverfault.com/questions/61915/how-do-i-make-ssh-fail-rather-than-prompt-for-a-password-if-the-public-key-authe
    child = pexpect_spawn("{} -oBatchMode=yes -p443 -T git@ssh.github.com".format(ssh_path), encoding="utf8")

    # GitHub prints 'Hi {username}!...' when attempting to get shell access
    try:
        i = child.expect(["Hi (.+)! You've successfully authenticated",
                          "Enter passphrase for key",
                          "Permission denied",
                          "Are you sure you want to continue connecting"])
    except pexpect.TIMEOUT:
        return None

    if ON_WINDOWS:
        child.kill(signal.SIGINT)
    else:
        child.close()

    if i == 0:
        username = child.match.groups()[0]
    else:
        return None

    # if repo is unspecified, default to usernae
    if repo is None:
        repo = username

    return User(name=username,
                repo=f"git+ssh://git@ssh.github.com:443/{org}/{repo}",
                org=org)


@contextlib.contextmanager
def _authenticate_https(org, repo=None):
    """Try authenticating via HTTPS, if succesful yields User, otherwise raises Error."""
    _CREDENTIAL_SOCKET.parent.mkdir(mode=0o700, exist_ok=True)
    try:
        git = Git()

        # Get credentials from cache if possible
        if not ON_WINDOWS:
            Git.cache = f"-c credential.helper= -c credential.helper='cache --socket {_CREDENTIAL_SOCKET}'"
            git = git.set(Git.cache)

            with _spawn(git("credential fill"), quiet=True) as child:
                child.sendline("protocol=https")
                child.sendline("host=github.com")
                child.sendline("")
                i = child.expect(["Username for '.+'", "Password for '.+'",
                                  "username=([^\r]+)\r\npassword=([^\r]+)\r\n"])
                if i == 2:
                    username, password = child.match.groups()
                else:
                    username = password = None
                    child.close()
                    child.exitstatus = 0

        if ON_WINDOWS or password is None:
            username = _prompt_username(_("GitHub username: "))
            password = _prompt_password(_("GitHub password: "))

        # Check if credentials are correct
        res = requests.get("https://api.github.com/user", auth=(username, password.encode('utf8')))

        # Check for 2-factor authentication https://developer.github.com/v3/auth/#working-with-two-factor-authentication
        if "X-GitHub-OTP" in res.headers:
            raise Error("Looks like you have two-factor authentication enabled!"
                        " Please generate a personal access token (with GitHub's `repo` scope) and use it as your password."
                        " See https://help.github.com/articles/creating-a-personal-access-token-for-the-command-line for more info.")

        if res.status_code != 200:
            logger.info(res.headers)
            logger.info(res.text)
            raise Error(_("Invalid username and/or password.") if res.status_code ==
                        401 else _("Could not authenticate user."))

        # Canonicalize (capitalization of) username,
        # Especially if user logged in via email address
        username = res.json()["login"]

        # If repo is unspecified, default to username
        if repo is None:
            repo = username

        if not ON_WINDOWS:
            # Credentials are correct, best cache them
            with _spawn(git("-c credentialcache.ignoresighup=true credential approve"), quiet=True) as child:
                child.sendline("protocol=https")
                child.sendline("host=github.com")
                child.sendline(f"path={org}/{username}")
                child.sendline(f"username={username}")
                child.sendline(f"password={password}")
                child.sendline("")

        global PASSWORD
        PASSWORD = password

        yield User(name=username,
                   repo=f"https://{username}@github.com/{org}/{repo}",
                   org=org)
    except BaseException:
        # Some error occured while this context manager is active, best forget credentials.
        logout()
        raise


def _prompt_username(prompt="Username: "):
    """Prompt the user for username."""
    try:
        username = input(prompt).strip()
        while not username:
            print("Username cannot be empty, please try again.")
            username = input(prompt).strip()
        return username
    except EOFError:
        print()


def _prompt_password(prompt="Password: "):
    """Prompt the user for password, printing asterisks for each character"""
    print(prompt, end="", flush=True)

    # List of UTF-8 chars in the password
    password = []
    # buffer containing the bytes of the char currently being read
    char_buffer = []

    getch = _Getch()


    # with _no_echo_stdin():
    while True:
        # Read one byte
        ch = getch()

        # If user presses Enter or ctrl-d
        if ch in (ord("\r"), ord("\n"), 4):
            print("\r")
            break
        # Del
        elif ch == 127 or ch == 8:
            if len(password) > 0:
                print("\b \b", end="", flush=True)
            # Remove last char and its corresponding bytes
            password.pop()
        # Ctrl-c
        elif ch == 3:
            print("^C", end="", flush=True)
            raise KeyboardInterrupt
        else:
            char_buffer.append(ch)
            # UTF-8 characters cannot be longer than 4 bytes
            if len(char_buffer) > 4:
                raise Error(_("Invalid characters detected in password"))

            try:
                char = bytes(char_buffer).decode("utf8")
            except UnicodeDecodeError:
                pass
            else:
                password.append(char)
                char_buffer.clear()
                print("*", end="", flush=True)


    if not password:
        print("Password cannot be empty, please try again.")
        return _prompt_password(prompt)

    return "".join(password)


class _Getch:
    """Gets a single character from standard input.  Does not echo to the
screen."""
    def __init__(self):
        self.impl = (_GetchWindows if ON_WINDOWS else _GetchUnix)()

    def __call__(self):
        return self.impl()


class _GetchUnix:
    def __call__(self):
        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)
        try:
            tty.setraw(sys.stdin.fileno())
            return ord(sys.stdin.buffer.read(1))
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)


class _GetchWindows:
    def __call__(self):
        return ord(msvcrt.getch())


def _escape_ansi(line):
    ansi_escape = re.compile(r'(?:\x1B[@-_]|[\x80-\x9F])[0-?]*[ -/]*[@-~]')
    return ansi_escape.sub('', line)
