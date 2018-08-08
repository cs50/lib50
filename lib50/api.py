import collections
import contextlib
import copy
import datetime
import gettext
import itertools
import logging
import os
import glob
from pathlib import Path
import pkg_resources
import re
import readline
import shutil
import shlex
import subprocess
import sys
import tempfile
import threading
import termios
import time
import tty

import attr
import pexpect
import requests
import termcolor
import yaml

from . import _
from .errors import *
from . import config as lib50_config

__all__ = ["push", "local", "working_area", "files", "connect", "prepare", "authenticate", "upload", "logout", "ProgressBar"]

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())

LOCAL_PATH = "~/.local/share/lib50"

_CREDENTIAL_SOCKET = Path("~/.git-credential-cache/lib50").expanduser()


def push(tool, slug, prompt=lambda included, excluded: True):
    """
    Push to github.com/org/repo=username/slug if tool exists.
    Returns username, commit hash
    """
    check_dependencies()

    org, (included, excluded) = connect(slug, tool)

    with authenticate(org) as user, prepare(tool, slug, user, included):
        if prompt(included, excluded):
            return upload(slug, user, tool)
        else:
            raise Error(_("No files were submitted."))


def local(slug, tool, offline=False):
    """
    Create/update local copy of github.com/org/repo/branch.
    Returns path to local copy
    """
    # Parse slug
    slug = Slug(slug, offline=offline)

    local_path = Path(LOCAL_PATH).expanduser() / slug.org / slug.repo

    git = Git(f"-C {shlex.quote(str(local_path))}")
    if not local_path.exists():
        _run(Git()(f"init {shlex.quote(str(local_path))}"))
        _run(git(f"remote add origin https://github.com/{slug.org}/{slug.repo}"))

    if not offline:
        _run(git(f"fetch origin {slug.branch}"))

    _run(git(f"checkout -B {slug.branch} origin/{slug.branch}"))
    _run(git(f"reset --hard HEAD"))

    problem_path = (local_path / slug.problem).absolute()

    if not problem_path.exists():
        raise InvalidSlugError(_("{} does not exist at {}/{}").format(slug.problem, slug.org, slug.repo))

    # Get config
    try:
        with open(problem_path / ".cs50.yaml") as f:
            try:
                config = lib50_config.load(f.read(), tool)
            except InvalidConfigError:
                raise InvalidSlugError(
                    _("Invalid slug for {}. Did you mean something else?").format(tool))
    except FileNotFoundError:
        raise InvalidSlugError(_("Invalid slug. Did you mean something else?"))

    return problem_path


@contextlib.contextmanager
def working_area(files, name=""):
    """
    Copy all files to a temporary directory (the working area)
    Optionally names the working area name
    Returns path to the working area
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
    origin = os.getcwd()
    try:
        os.chdir(dest)
        yield dest
    finally:
        os.chdir(origin)


def files(patterns, root=".", always_exclude=["**/.git*", "**/.lfs*", "**/.c9*", "**/.~c9*"]):
    """
    Takes a list of lib50.config.FilePatterns returns which files should be included and excluded from cwd.
    """
    with cd(root):
        # Include everything by default
        included = _glob("*")
        excluded = set()

        if patterns:
            missing_files = []

            # Per line in files
            for item in patterns:
                # Include all files that are tagged with !require
                if item.type is lib50_config.PatternType.Required:
                    file = str(Path(item.pattern))
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
                elif item.type is lib50_config.PatternType.Included:
                    new_included = _glob(item.pattern)
                    excluded -= new_included
                    included.update(new_included)
                # Exclude all files that are tagged with !exclude
                else:
                    new_excluded = _glob(item.pattern)
                    included -= new_excluded
                    excluded.update(new_excluded)

            if missing_files:
                raise MissingFilesError(missing_files)

    # Exclude all files that match a pattern from always_exclude
    for line in always_exclude:
        included -= _glob(line)

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


def connect(slug, tool):
    """
    Ensure .cs50.yaml and tool key exists, raises Error otherwise
    Check that all required files as per .cs50.yaml are present
    Returns tool specific portion of .cs50.yaml
    """
    with ProgressBar(_("Connecting")):
        # Parse slug
        slug = Slug(slug)

        # Get .cs50.yaml
        try:
            config = lib50_config.load(_get_content(slug.org, slug.repo,
                                                 slug.branch, slug.problem / ".cs50.yaml"), tool)
        except InvalidConfigError:
            raise InvalidSlugError(_("Invalid slug for {}. Did you mean something else?").format(tool))

        if not config:
            raise InvalidSlugError(_("Invalid slug for {}. Did you mean something else?").format(tool))

        # If config of tool is just a truthy value, config should be empty
        if not isinstance(config, dict):
            config = {}

        org = config.get("org", tool)
        included, excluded = files(config.get("files"))

        # Check that at least 1 file is staged
        if not included:
            raise Error(_("No files in this directory are expected for submission."))

        return org, (included, excluded)


@contextlib.contextmanager
def authenticate(org):
    """
    Authenticate with GitHub via SSH if possible
    Otherwise authenticate via HTTPS
    Returns an authenticated User
    """
    with ProgressBar(_("Authenticating")) as progress_bar:
        user = _authenticate_ssh(org)
        progress_bar.stop()
        if user is None:
            with _authenticate_https(org) as user:
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
        Git.working_area = f"-C {area}"
        git = Git(Git.working_area)
        # Clone just .git folder
        try:
            _run(git.set(Git.cache)(f"clone --bare {user.repo} .git"))
        except Error:
            raise Error(_("Looks like {} isn't enabled for your account yet. "
                          "Go to https://cs50.me/authorize and make sure you accept any pending invitations!".format(tool)))

        _run(git("config --bool core.bare false"))
        _run(git(f"config --path core.worktree {area}"))

        try:
            _run(git("checkout --force {} .gitattributes".format(branch)))
        except Error:
            pass

        # Set user name/email in repo config
        _run(git(f"config user.email {shlex.quote(user.email)}"))
        _run(git(f"config user.name {shlex.quote(user.name)}"))

        # Switch to branch without checkout
        _run(git(f"symbolic-ref HEAD refs/heads/{branch}"))

        # Git add all included files
        for f in included:
            _run(git(f"add {f}"))

        # Remove gitattributes from included
        if Path(".gitattributes").exists() and ".gitattributes" in included:
            included.remove(".gitattributes")

        # Add any oversized files through git-lfs
        _lfs_add(included, git)

        progress_bar.stop()
        yield


def upload(branch, user, tool):
    """
    Commit + push to branch
    Returns username, commit hash
    """
    with ProgressBar(_("Uploading")):
        language = os.environ.get("LANGUAGE")
        commit_message = _("automated commit by {}{}").format(tool, f" [{language}]" if language else "")

        # Commit + push
        git = Git(Git.working_area)
        _run(git(f"commit -m {shlex.quote(commit_message)} --allow-empty"))
        _run(git.set(Git.cache)(f"push origin {branch}"))
        commit_hash = _run(git("rev-parse HEAD"))
        return user.name, commit_hash


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
    email = attr.ib(default=attr.Factory(lambda self: f"{self.name}@users.noreply.github.com",
                                         takes_self=True),
                    init=False)


class Git:
    cache = ""
    working_area = ""

    def __init__(self, *args):
        self._args = args

    def set(self, arg):
        return Git(*self._args, arg)

    def __call__(self, command):
        git_command = f"git {' '.join(self._args)} {command}"
        git_command = re.sub(' +', ' ', git_command)

        # Format to show in git info
        logged_command = git_command
        for opt in [Git.cache, Git.working_area]:
            logged_command = logged_command.replace(str(opt), "")
        logged_command = re.sub(' +', ' ', logged_command)

        # Log pretty command in info
        logger.info(termcolor.colored(logged_command, attrs=["bold"]))

        # Log actual command in debug
        logger.debug(git_command)

        return git_command


class Slug:
    def __init__(self, slug, offline=False):
        """Parse <org>/<repo>/<branch>/<problem_dir> from slug."""
        self.slug = slug
        self.offline = offline

        # Assert begin/end of slug are correct
        self._check_endings()

        # Find third "/" in identifier
        idx = slug.find("/", slug.find("/") + 1)
        if idx == -1:
            raise InvalidSlugError(_("Invalid slug"))

        # Split slug in <org>/<repo>/<remainder>
        remainder = slug[idx + 1:]
        self.org, self.repo = slug.split("/")[:2]

        # Find a matching branch
        for branch in self._get_branches():
            if remainder.startswith(f"{branch}"):
                self.branch = branch
                self.problem = Path(remainder[len(branch) + 1:])
                break
        else:
            raise InvalidSlugError(_("Invalid slug {}".format(slug)))

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
            local_path = Path(LOCAL_PATH).expanduser() / self.org / self.repo
            get_refs = f"git -C {shlex.quote(str(local_path))} show-ref --heads"
        else:
            get_refs = f"git ls-remote --heads https://github.com/{self.org}/{self.repo}"
        try:
            return (line.split()[1].replace("refs/heads/", "") for line in _run(get_refs, timeout=3).split("\n"))
        except Error:
            return []


class ProgressBar:
    """Show a progress bar starting with message."""
    DISABLED = False
    TICKS_PER_SECOND = 2

    def __init__(self, message):
        self._message = message
        self._progressing = False
        self._thread = None

    def stop(self):
        """Stop the progress bar."""
        if self._progressing:
            self._progressing = False
            self._thread.join()

    def __enter__(self):
        def progress_runner():
            print(f"{self._message}...", end="", flush=True)
            while self._progressing:
                print(".", end="", flush=True)
                time.sleep(1 / ProgressBar.TICKS_PER_SECOND if ProgressBar.TICKS_PER_SECOND else 0)
            print()

        if not ProgressBar.DISABLED:
            self._progressing = True
            self._thread = threading.Thread(target=progress_runner)
            self._thread.start()
        else:
            print(f"{self._message}...")

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
def _spawn(command, quiet=False, timeout=None):
    # Spawn command
    child = pexpect.spawn(
        command,
        encoding="utf-8",
        env=dict(os.environ),
        timeout=timeout)

    try:
        if not quiet:
            child.logfile_read = _StreamToLogger(logger.debug)
        yield child
    except:
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


def _run(command, quiet=False, timeout=None):
    """Run a command, returns command output."""
    try:
        with _spawn(command, quiet, timeout) as child:
            command_output = child.read().strip().replace("\r\n", "\n")
    except pexpect.TIMEOUT:
        logger.info(f"command {command} timed out")
        raise Error()

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


def _get_content(org, repo, branch, filepath):
    """Get all content from org/repo/branch/filepath at GitHub."""
    url = "https://github.com/{}/{}/raw/{}/{}".format(org, repo, branch, filepath)
    r = requests.get(url)
    if not r.ok:
        if r.status_code == 404:
            raise InvalidSlugError(_("Invalid slug. Did you mean to submit something else?"))
        else:
            raise Error(_("Could not connect to GitHub."))
    return r.content


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
                      "and then re-run {}!").format("\n".join(huges), org))

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
            _run(git("rm --cached {}".format(shlex.quote(large))))
            _run(git("lfs track {}".format(shlex.quote(large))))
            _run(git("add {}".format(shlex.quote(large))))
        _run(git("add --force .gitattributes"))


def _authenticate_ssh(org):
    """Try authenticating via ssh, if succesful yields a User, otherwise raises Error."""
    # Require ssh-agent
    child = pexpect.spawn("ssh -T git@github.com", encoding="utf8")
    # GitHub prints 'Hi {username}!...' when attempting to get shell access
    i = child.expect(["Hi (.+)! You've successfully authenticated", "Enter passphrase for key",
                      "Permission denied", "Are you sure you want to continue connecting"])
    child.close()
    if i == 0:
        username = child.match.groups()[0]
        return User(name=username,
                    repo=f"git@github.com:{org}/{username}")


@contextlib.contextmanager
def _authenticate_https(org):
    """Try authenticating via HTTPS, if succesful yields User, otherwise raises Error."""
    _CREDENTIAL_SOCKET.parent.mkdir(mode=0o700, exist_ok=True)
    try:
        Git.cache = f"-c credential.helper= -c credential.helper='cache --socket {_CREDENTIAL_SOCKET}'"
        git = Git(Git.cache)

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

        if password is None:
            username = _prompt_username(_("GitHub username: "))
            password = _prompt_password(_("GitHub password: "))

        res = requests.get("https://api.github.com/user", auth=(username, password))

        # Check for 2-factor authentication https://developer.github.com/v3/auth/#working-with-two-factor-authentication
        if "X-GitHub-OTP" in res.headers:
            raise Error("Looks like you have two-factor authentication enabled!"
                        " Please generate a personal access token and use it as your password."
                        " See https://help.github.com/articles/creating-a-personal-access-token-for-the-command-line for more info.")

        if res.status_code != 200:
            logger.info(res.headers)
            logger.info(res.text)
            raise Error(_("Invalid username and/or password.") if res.status_code ==
                        401 else _("Could not authenticate user."))

        # Canonicalize (capitalization of) username,
        # Especially if user logged in via email address
        username = res.json()["login"]

        with _spawn(git("-c credentialcache.ignoresighup=true credential approve"), quiet=True) as child:
            child.sendline("protocol=https")
            child.sendline("host=github.com")
            child.sendline(f"path={org}/{username}")
            child.sendline(f"username={username}")
            child.sendline(f"password={password}")
            child.sendline("")

        yield User(name=username,
                   repo=f"https://{username}@github.com/{org}/{username}")
    except:
        logout()
        raise


def _prompt_username(prompt="Username: ", prefill=None):
    """Prompt the user for username."""
    if prefill:
        readline.set_startup_hook(lambda: readline.insert_text(prefill))

    try:
        return input(prompt).strip()
    except EOFError:
        print()
    finally:
        readline.set_startup_hook()


def _prompt_password(prompt="Password: "):
    """Prompt the user for password."""
    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    tty.setraw(fd)

    print(prompt, end="", flush=True)
    password = []
    try:
        while True:
            ch = sys.stdin.buffer.read(1)[0]
            if ch in (ord("\r"), ord("\n"), 4):  # If user presses Enter or ctrl-d
                print("\r")
                break
            elif ch == 127:  # DEL
                try:
                    password.pop()
                except IndexError:
                    pass
                else:
                    print("\b \b", end="", flush=True)
            elif ch == 3:  # ctrl-c
                print("^C", end="", flush=True)
                raise KeyboardInterrupt
            else:
                password.append(ch)
                print("*", end="", flush=True)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)

    return bytes(password).decode()
