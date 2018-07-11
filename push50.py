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

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())

LOCAL_PATH = "~/.local/share/push50"

_CREDENTIAL_SOCKET = Path("~/.git-credential-cache/push50").expanduser()

# Internationalization
gettext.install("push50", pkg_resources.resource_filename("push50", "locale"))


def push(org, slug, tool, prompt=lambda included, excluded: True):
    """
    Push to github.com/org/repo=username/slug if tool exists
    Returns username, commit hash
    """
    check_dependencies()

    config = connect(slug, tool)

    with authenticate(org) as user:
        with prepare(org, slug, user, config) as (included, excluded):
            if prompt(included, excluded):
                return upload(slug, user)
            else:
                raise Error(_("No files were submitted."))


def local(slug, tool, offline=False):
    """
    Create/update local copy of github.com/org/repo/branch
    Returns path to local copy
    """
    # parse slug
    slug = Slug(slug, offline=offline)

    local_path = Path(LOCAL_PATH).expanduser() / slug.org / slug.repo

    if local_path.exists():
        git = Git("-C {local_path}")
        # switch to branch
        _run(git(f"checkout {slug.branch}"))

        if not offline:
            # pull new commits
            _run(git("fetch"))
    else:
        # clone repo to local_path
        _run(Git()(f"clone -b {slug.branch} https://github.com/{slug.org}/{slug.repo} {local_path}"))

    problem_path = (local_path / slug.problem).absolute()

    if not problem_path.exists():
        raise InvalidSlug(_("{} does not exist at {}/{}").format(slug.problem, slug.org, slug.repo))

    # get config
    try:
        with open(problem_path / ".cs50.yaml", "r") as f:
            config = yaml.safe_load(f.read())
            if tool not in config or not config[tool]:
                raise InvalidSlug(_("Invalid slug for {}. Did you mean something else?").format(tool))
    except FileNotFoundError:
        raise InvalidSlug(_("Invalid slug. Did you mean something else?"))

    return problem_path


def files(config, always_exclude=[".git*", ".lfs*", ".c9*", ".~c9*"]):
    """
    From config (exclude + required keys) decide which files are included and excluded
    First exclude is interpeted as .gitignore
    Then all entries from required are included
    Finally any entries in the always_exclude optional arg are excluded
    Returns included_files, excluded_files
    """
    included = set(glob.glob("*"))
    excluded = set()
    if "exclude" in config:
        for line in config["exclude"]:
            if line.startswith("!"):
                new_included = set(glob.glob(line[1:]))
                excluded -= new_included
                included.update(new_included)
            else:
                new_excluded = set(glob.glob(line))
                included -= new_excluded
                excluded.update(new_excluded)

        if "required" in config:
            for line in config["required"]:
                new_included = set(glob.glob(line))
                excluded -= new_included
                included.update(new_included)

    for line in always_exclude:
        new_excluded = set(glob.glob(line[1:]))
        included -= new_excluded
        excluded.update(new_excluded)

    # Exclude any file names that are not valid UTF-8
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
    returns tool specific portion of .cs50.yaml
    """
    with ProgressBar(_("Connecting")):
        # parse slug
        slug = Slug(slug)

        # get .cs50.yaml
        try:
            config = yaml.safe_load(_get_content(slug.org, slug.repo,
                                                 slug.branch, slug.problem / ".cs50.yaml")).get(tool)
        except yaml.YAMLError:
            raise InvalidSlug(_("Invalid slug for {}. Did you mean something else?").format(tool))

        if not config:
            raise InvalidSlug(_("Invalid slug for {}. Did you mean something else?").format(tool))

        if not isinstance(config, dict):
            config = {}

        # check that all required files are present
        _check_required(config)

        return config


@contextlib.contextmanager
def authenticate(org):
    """
    Authenticate with GitHub via SSH if possible
    Otherwise authenticate via HTTPS
    returns: an authenticated User
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
def prepare(org, branch, user, config):
    """
    Prepare git for pushing
    Check that there are no permission errors
    Add necessities to git config
    Stage files
    Stage files via lfs if necessary
    Check that atleast one file is staged
    """
    with ProgressBar(_("Preparing")) as progress_bar, tempfile.TemporaryDirectory() as git_dir:
        Git.work_tree = f"--work-tree={os.getcwd()}"
        Git.git_dir = f"--git-dir={git_dir}"
        git = Git(Git.work_tree, Git.git_dir)

        # clone just .git folder
        try:
            with _spawn(git.set(Git.cache)(f"clone --bare {user.repo} {git_dir}")) as child:
                if user.password and child.expect(["Password for '.*': ", pexpect.EOF]) == 0:
                    child.sendline(user.password)
        except Error:
            if user.password:
                e = Error(_("Looks like {} isn't enabled for your account yet. "
                            "Go to https://cs50.me/authorize and make sure you accept any pending invitations!".format(org)))
            else:
                e = Error(_("Looks {0} isn't yet enabled for your account. "
                            "Log into https://cs50.me/ in a browser, "
                            "click \"Authorize application\" if prompted, and re-run {0} here.".format(org)))
            raise e

        # shadow any user specified .gitattributes (necessary evil for using git lfs for oversized files)
        with _shadow(".gitattributes") as hidden_gitattributes:
            try:
                _run(git("checkout --force {} .gitattributes".format(branch)))
            except Error:
                pass

            # set user name/email in repo config
            _run(git(f"config user.email {shlex.quote(user.email)}"))
            _run(git(f"config user.name {shlex.quote(user.name)}"))

            # switch to branch without checkout
            _run(git(f"symbolic-ref HEAD refs/heads/{branch}"))

            import pdb; pdb.set_trace()
            # decide on files to include, exclude
            included, excluded = files(config)

            # git add all included files
            for f in included:
                _run(git(f"add --force {f}"))

            # remove gitattributes from files
            if Path(".gitattributes").exists() and ".gitattributes" in files:
                files.remove(".gitattributes")

            # remove the shadowed gitattributes from excluded_files
            if hidden_gitattributes.name in excluded:
                excluded.remove(hidden_gitattributes.name)

            # check that at least 1 file is staged
            if not included:
                raise Error(_("No files in this directory are expected for submission."))

            # add any oversized files through git-lfs
            _lfs_add(included, git)

            progress_bar.stop()
            yield included, excluded

def upload(branch, user):
    """
    Commit + push to branch
    Returns username, commit hash
    """
    with ProgressBar(_("Uploading")):
        # decide on commit message
        headers = requests.get("https://api.github.com/").headers
        commit_message = datetime.datetime.strptime(headers["Date"], "%a, %d %b %Y %H:%M:%S %Z")
        commit_message = commit_message.strftime("%Y%m%dT%H%M%SZ")

        # commit + push
        git = Git(Git.work_tree, Git.git_dir)
        _run(git(f"commit -m {commit_message} --allow-empty"))
        with _spawn(git.set(Git.cache)(f"push origin {branch}")) as child:
            if user.password and child.expect(["Password for '.*': ", pexpect.EOF]) == 0:
                child.sendline(user.password)

        commit_hash = _run(git("rev-parse HEAD"))
        return user.name, commit_hash


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
    if not matches or pkg_resources.parse_version(matches.group(1)) < pkg_resources.parse_version("2.7.0"):
        raise Error(_("You have an old version of git. Install version 2.7 or later, then re-run!"))

def logout():
    _run(f"git credential-cache --socket {_CREDENTIAL_SOCKET} exit")

class Error(Exception):
    pass

class InvalidSlug(Error):
    pass

@attr.s(slots=True)
class User:
    name = attr.ib()
    password = attr.ib()
    repo = attr.ib()
    email = attr.ib(default=attr.Factory(lambda self: f"{self.name}@users.noreply.github.com",
                                         takes_self=True),
                    init=False)

class Git:
    cache = ""
    git_dir = ""
    work_tree = ""

    def __init__(self, *args):
        self._args = args

    def set(self, arg):
        return Git(*self._args, arg)

    def __call__(self, command):
        git_command = f"git {' '.join(self._args)} {command}"
        git_command = re.sub(' +', ' ', git_command)

        # format to show in git info
        logged_command = git_command
        for opt in [Git.cache, Git.git_dir, Git.work_tree]:
            logged_command = logged_command.replace(opt, "")
        logged_command = re.sub(' +', ' ', logged_command)

        # log pretty command in info
        logger.info(termcolor.colored(logged_command, attrs=["bold"]))

        # log actual command in debug
        logger.debug(git_command)

        return git_command

class Slug:
    def __init__(self, slug, offline=False):
        """ parse <org>/<repo>/<branch>/<problem_dir> from slug """
        self.slug = slug
        self.offline = offline

        # assert begin/end of slug are correct
        self._check_endings()

        # Find third "/" in identifier
        idx = slug.find("/", slug.find("/") + 1)
        if idx == -1:
            raise InvalidSlug(_("Invalid slug"))

        # split slug in <org>/<repo>/<remainder>
        remainder = slug[idx + 1:]
        self.org, self.repo = slug.split("/")[:2]

        # find a matching branch
        for branch in self._get_branches():
            if remainder.startswith(f"{branch}"):
                self.branch = branch
                self.problem = Path(remainder[len(branch) + 1:])
                break
        else:
            raise InvalidSlug(_("Invalid slug {}".format(slug)))

    def _check_endings(self):
        """ check begin/end of slug, raises Error if malformed """
        if self.slug.startswith("/") and self.slug.endswith("/"):
            raise InvalidSlug(
                _("Invalid slug. Did you mean {}, without the leading and trailing slashes?".format(self.slug.strip("/"))))
        elif self.slug.startswith("/"):
            raise InvalidSlug(
                _("Invalid slug. Did you mean {}, without the leading slash?".format(self.slug.strip("/"))))
        elif self.slug.endswith("/"):
            raise InvalidSlug(
                _("Invalid slug. Did you mean {}, without the trailing slash?".format(self.slug.strip("/"))))

    def _get_branches(self):
        """ get branches from org/repo """
        if self.offline:
            get_refs = f"git -C {Path(LOCAL_PATH) / self.org / self.repo} show-ref --heads"
        else:
            get_refs = f"git ls-remote --heads https://github.com/{self.org}/{self.repo}"
        try:
            return (line.split()[1].replace("refs/heads/", "") for line in _run(get_refs, timeout=3).split("\n"))
        except Error:
            return []


class ProgressBar:
    """ Show a progress bar starting with message """
    DISABLED = False
    TICKS_PER_SECOND = 2

    def __init__(self, message):
        self._message = message
        self._progressing = False
        self._thread = None

    def stop(self):
        """Stop the progress bar"""
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
    """
    Send all that enters the stream to log-function
    """

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
    # spawn command
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
        # Drain output from process while we wait for it to quit
        while child.isalive():
            try:
                child.read_nonblocking(timeout=0)
            except pexpect.TIMEOUT:
                pass
            except pexpect.EOF:
                child.wait()
                break
        child.close()
        if child.signalstatus is None and child.exitstatus != 0:
            logger.debug("{} exited with {}".format(command, child.exitstatus))
            raise Error()


def _run(command, quiet=False, timeout=None):
    """ Run a command, returns command output """

    try:
        with _spawn(command, quiet, timeout) as child:
            command_output = child.read().strip().replace("\r\n", "\n")
    except pexpect.TIMEOUT:
        logger.info(f"command {command} timed out")
        raise Error()

    return command_output


def _get_content(org, repo, branch, filepath):
    """ Get all content from org/repo/branch/filepath at GitHub """
    url = "https://github.com/{}/{}/raw/{}/{}".format(org, repo, branch, filepath)
    r = requests.get(url)
    if not r.ok:
        if r.status_code == 404:
            raise InvalidSlug(_("Invalid slug. Did you mean to submit something else?"))
        else:
            raise Error(_("Could not connect to GitHub."))
    return r.content

def _check_required(config):
    """ Check that all required files are present """

    if "required" not in config:
        return

    missing = [f for f in config["required"] if not os.path.exists(f)]

    if missing:
        msg = "{}\n{}\n{}".format(
            _("You seem to be missing these files:"),
            "\n".join(missing),
            _("Ensure you have the required files before submitting."))
        raise Error(msg)

def _lfs_add(files, git):
    """
    Add any oversized files with lfs
    Throws error if a file is bigger than 2GB or git-lfs is not installed
    """
    # check for large files > 100 MB (and huge files > 2 GB)
    # https://help.github.com/articles/conditions-for-large-files/
    # https://help.github.com/articles/about-git-large-file-storage/
    larges, huges = [], []
    for file in files:
        size = os.path.getsize(file)
        if size > (100 * 1024 * 1024):
            larges.append(file)
        elif size > (2 * 1024 * 1024 * 1024):
            huges.append(file)

    # raise Error if a file is >2GB
    if huges:
        raise Error(_("These files are too large to be submitted:\n{}\n"
                      "Remove these files from your directory "
                      "and then re-run {}!").format("\n".join(huges), org))

    # add large files (>100MB) with git-lfs
    if larges:
        # raise Error if git-lfs not installed
        if not shutil.which("git-lfs"):
            raise Error(_("These files are too large to be submitted:\n{}\n"
                          "Install git-lfs (or remove these files from your directory) "
                          "and then re-run!").format("\n".join(larges)))

        # install git-lfs for this repo
        _run(git("lfs install --local"))

        # for pre-push hook
        _run(git("config credential.helper cache"))

        # rm previously added file, have lfs track file, add file again
        for large in larges:
            _run(git("rm --cached {}".format(shlex.quote(large))))
            _run(git("lfs track {}".format(shlex.quote(large))))
            _run(git("add {}".format(shlex.quote(large))))
        _run(git("add --force .gitattributes"))


@contextlib.contextmanager
def _shadow(filepath):
    """
    Temporarily shadow filepath, allowing you to safely create a file at filepath
    When entering:
    - renames file at filepath to unique hidden name
    When exiting:
    - removes file
    - restores file (if it existed in the first place)
    Yields the hidden_path (only exists if filepath exists)
    """
    filepath = Path(filepath).absolute()
    hidden_path = filepath.parent / f".shadowed_{filepath.name}_{round(time.time())}"
    is_shadowing = filepath.exists()
    if is_shadowing:
        os.rename(filepath, hidden_path)

    yield hidden_path

    if filepath.exists():
        os.remove(filepath)
    if is_shadowing:
        os.rename(hidden_path, filepath)


def _authenticate_ssh(org):
    """ Try authenticating via ssh, if succesful yields a User, otherwise raises Error """
    # require ssh-agent
    child = pexpect.spawn("ssh -T git@github.com", encoding="utf8")
    # github prints 'Hi {username}!...' when attempting to get shell access
    i = child.expect(["Hi (.+)! You've successfully authenticated", "Enter passphrase for key",
                      "Permission denied", "Are you sure you want to continue connecting"])
    child.close()
    if i == 0:
        username = child.match.groups()[0]
        return User(name=username,
                    password=None,
                    repo=f"git@github.com:{org}/{username}")


@contextlib.contextmanager
def _authenticate_https(org):
    """ Try authenticating via HTTPS, if succesful yields User, otherwise raises Error """

    _CREDENTIAL_SOCKET.parent.mkdir(mode=0o700, exist_ok=True)
    try:
        Git.cache = f"-c credential.helper= -c credential.helper='cache --socket {_CREDENTIAL_SOCKET}'"
        git = Git(Git.cache)

        with _spawn(git("credential fill"), quiet=True) as child:
            child.sendline("protocol=https")
            child.sendline("host=github.com")
            child.sendline("")
            i = child.expect(["Username for '.+'", "Password for '.+'", "username=([^\r]+)\r\npassword=([^\r]+)\r\n"])
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

        # check for 2-factor authentication http://github3.readthedocs.io/en/develop/examples/oauth.html?highlight=token
        if "X-GitHub-OTP" in res.headers:
            raise Error("Looks like you have two-factor authentication enabled!"
                        " Please generate a personal access token and use it as your password."
                        " See https://help.github.com/articles/creating-a-personal-access-token-for-the-command-line for more info.")

        if res.status_code != 200:
            logger.info(res.headers)
            logger.info(res.text)
            raise Error(_("Invalid username and/or password.") if res.status_code ==
                        401 else _("Could not authenticate user."))

        # canonicalize (capitalization of) username,
        # especially if user logged in via email address
        username = res.json()["login"]

        with _spawn(git("-c credentialcache.ignoresighup=true credential approve"), quiet=True) as child:
            child.sendline("protocol=https")
            child.sendline("host=github.com")
            child.sendline(f"path={org}/{username}")
            child.sendline(f"username={username}")
            child.sendline(f"password={password}")
            child.sendline("")

        yield User(name=username,
                   password=password,
                   repo=f"https://{username}@github.com/{org}/{username}")
    except:
        logout()
        raise


def _prompt_username(prompt="Username: ", prefill=None):
    """ Prompt the user for username """
    if prefill:
        readline.set_startup_hook(lambda: readline.insert_text(prefill))

    try:
        return input(prompt).strip()
    except EOFError:
        print()
    finally:
        readline.set_startup_hook()


def _prompt_password(prompt="Password: "):
    """ Prompt the user for password """
    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    tty.setraw(fd)

    print(prompt, end="", flush=True)
    password = []
    try:
        while True:
            ch = sys.stdin.buffer.read(1)[0]
            if ch in (ord("\r"), ord("\n"), 4):  # if user presses Enter or ctrl-d
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

# TODO remove
if __name__ == "__main__":
    ProgressBar.DISABLED = True
    push("submit50", "cs50/problems/2018/x/project", "submit50")

    #LOCAL_PATH = "./test"
    #print(local("cs50/problems2/master/hello", "check50"))
    pass
