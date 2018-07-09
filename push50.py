import collections
import contextlib
import copy
import datetime
import gettext
import glob
import itertools
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
import termios
import time
import tty

import attr
from git import Git, GitError, Repo, SymbolicReference, NoSuchPathError
import pexpect
import requests
import termcolor
import yaml

# logging.basicConfig(level="INFO")
QUIET = False
LOCAL_PATH = "~/.local/share/push50"

# Internationalization
gettext.install("messages", pkg_resources.resource_filename("push50", "locale"))

def push(org, slug, tool, prompt = (lambda included, excluded : True)):
    """
    Push to github.com/org/repo=username/slug if tool exists
    Returns username, commit hash
    """
    check_dependencies()

    config = connect(slug, tool)

    with authenticate(org) as user:
        with prepare(org, slug, user, config) as repository:
            if prompt(repository.included, repository.excluded):
                return upload(repository, slug, user)
            else:
                raise Error("No files were submitted.")

def local(slug, tool, update=True):
    """
    Create/update local copy of github.com/org/repo/branch
    Returns path to local copy + config
    """
    # parse slug
    if update:
        slug = Slug(slug)
    else:
        try:
            slug = Slug(slug, offline=True)
        except InvalidSlug:
            slug = Slug(slug)

    local_path = Path(LOCAL_PATH) / slug.org / slug.repo

    if local_path.exists():
        git = lambda command : f"git --git-dir={local_path / '.git'} --work-tree={local_path} {command}"

        # switch to branch
        _run(git(f"checkout {slug.branch}"))

        # pull new commits if update=True
        if update:
            _run(git("fetch"))
    else:
        # clone repo to local_path
        _run(f"git clone -b {slug.branch} https://github.com/{slug.org}/{slug.repo} {local_path}")

    problem_path = (local_path / slug.problem).absolute()

    if not problem_path.exists():
        raise InvalidSlug(f"{slug.problem} does not exist at {slug.org}/{slug.repo}")

    # get tool_yaml
    try:
        with open(problem_path / ".cs50.yaml", "r") as f:
            try:
                config = yaml.safe_load(f.read())[tool]
            except KeyError:
                raise InvalidSlug("Invalid slug for {}, did you mean something else?".format(tool))
    except FileNotFoundError:
        raise InvalidSlug("Invalid slug, did you mean something else?")

    # if problem is not referencing root of repo
    if slug.problem != Path("."):
        # merge root .cs50.yaml with local .cs50.yaml
        try:
            with open(local_path / ".cs50.yaml", "r") as f:
                root_config = yaml.safe_load(f.read())[tool]
        except (FileNotFoundError, KeyError):
            pass
        else:
            config = _merge_config(config, root_config)

    return problem_path, config

def connect(slug, tool):
    """
    Ensure .cs50.yaml and tool key exists, raises Error otherwise
    Check that all required files as per .cs50.yaml are present
    returns tool specific portion of .cs50.yaml
    """
    with ProgressBar("Connecting"):
        # parse slug
        slug = Slug(slug)

        # get .cs50.yaml
        try:
            config = yaml.safe_load(_get_content(slug.org, slug.repo, slug.branch, slug.problem / ".cs50.yaml"))[tool]
        except (yaml.YAMLError, KeyError):
            raise InvalidSlug("Invalid slug for {}, did you mean something else?".format(tool))


        # get .cs50.yaml from root if exists and merge with local
        try:
            root_config = yaml.safe_load(_get_content(slug.org, slug.repo, slug.branch, ".cs50.yaml"))[tool]
        except (Error, KeyError):
            pass
        else:
            config = _merge_config(config, root_config)

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
    with ProgressBar("Authenticating") as progress_bar:
        user = _authenticate_ssh(org)
        if user is None:
            progress_bar.stop()
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
    with ProgressBar("Preparing") as progress_bar, tempfile.TemporaryDirectory() as git_dir:
        git = lambda command : f"git --git-dir={git_dir} --work-tree={os.getcwd()} {command}"

        # clone just .git folder
        try:
            with _spawn(git(f"clone --bare {user.repo} {git_dir}")) as child:
                child.expect("Password for .+:")
                if user.password:
                    child.sendline(user.password)

        except Error:
            if user.password:
                e = Error(_("Looks like {} isn't enabled for your account yet. "
                            "Go to https://cs50.me/authorize and make sure you accept any pending invitations!".format(org)))
            else:
                e = Error(_("Looks {} isn't yet enabled for your account. "
                            "Log into https://cs50.me/ in a browser, "
                            "click \"Authorize application\" if prompted, and re-run {} here.".format(org, org)))
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

            # add exclude file
            exclude = _create_exclude(config)
            exclude_path = f"{git_dir}/info/exclude"
            with open(exclude_path, "w") as f:
                f.write(exclude + "\n")
                f.write(".git*\n")
                f.write(".lfs*\n")
            _run(git(f"config core.excludesFile {exclude_path}"))

            # add files to staging area
            _run(git("add --all"))

            # get file lists
            files = _run(git("ls-files")).replace("\r\n", "\n").split("\n")
            excluded_files = _run(git("ls-files --other")).replace("\r\n", "\n").split("\n")

            # remove gitattributes from files
            if Path(".gitattributes").exists() and ".gitattributes" in files:
                files.remove(".gitattributes")

            # remove the shadowed gitattributes from excluded_files
            if hidden_gitattributes.name in excluded_files:
                excluded_files.remove(hidden_gitattributes.name)

            # remove all empty strings from excluded_files
            excluded_files = [f for f in excluded_files if f]

            # add any oversized files through git-lfs
            _add_with_lfs(files, git)

            # check that at least 1 file is staged
            if not files:
                raise Error(_("No files in this directory are expected for submission."))

            progress_bar.stop()
            yield Repository(git, files, excluded_files)

def upload(repository, branch, user):
    """
    Commit + push to branch
    Returns username, commit hash
    """
    with ProgressBar("Uploading"):
        # decide on commit message
        headers = requests.get("https://api.github.com/").headers
        commit_message = datetime.datetime.strptime(headers["Date"], "%a, %d %b %Y %H:%M:%S %Z")
        commit_message = commit_message.strftime("%Y%m%dT%H%M%SZ")

        # commit + push
        _run(repository.git(f"commit -m {commit_message} --allow-empty"))
        with _spawn(repository.git(f"push origin {branch}")) as child:
            child.expect("Password for .+:")
            if user.password:
                child.sendline(password)

        commit_hash = _run(repository.git("rev-parse HEAD"))
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

class Error(Exception):
    pass

class ConnectionError(Error):
    pass

class InvalidSlug(Error):
    pass


@attr.s
class User:
    name = attr.ib()
    password = attr.ib()
    repo = attr.ib()
    email = attr.ib(default=attr.Factory(lambda self: f"{self.name}@users.noreply.github.com",
                                         takes_self=True))


@attr.s
class Repository:
    git = attr.ib()
    included = attr.ib(default=[])
    excluded = attr.ib(default=[])


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
            raise InvalidSlug("Invalid slug {}".format(slug))

        # split slug in <org>/<repo>/<remainder>
        remainder = slug[idx+1:]
        self.org, self.repo = slug.split("/")[:2]

        # find a matching branch
        for branch in self._get_branches():
            if remainder.startswith(f"{branch}"):
                self.branch = branch
                self.problem = Path(remainder[len(branch)+1:])
                break
        else:
            raise InvalidSlug("Invalid slug {}".format(slug))

    def _check_endings(self):
        """ check begin/end of slug, raises InvalidSlug if malformed """
        if self.slug.startswith("/") and self.slug.endswith("/"):
            raise InvalidSlug(_("Invalid slug. Did you mean {}, without the leading and trailing slashes?".format(self.slug.strip("/"))))
        elif self.slug.startswith("/"):
            raise InvalidSlug(_("Invalid slug. Did you mean {}, without the leading slash?".format(self.slug.strip("/"))))
        elif self.slug.endswith("/"):
            raise InvalidSlug(_("Invalid slug. Did you mean {}, without the trailing slash?".format(self.slug.strip("/"))))

    def _get_branches(self):
        """ get branches from org/repo """
        try:
            if self.offline:
                return map(str, Repo(f"{str(LOCAL_PATH)}/{self.org}/{self.repo}").branches)
            else:
                return (line.split("\t")[1].replace("refs/heads/", "")
                        for line in Git().ls_remote(f"https://github.com/{self.org}/{self.repo}", heads=True).split("\n"))
        except (GitError, NoSuchPathError):
            return []


class ProgressBar:
    """ Show a progress bar starting with message """
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
                time.sleep(0.5)
            print()

        if not QUIET:
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
    Except any message that contains a message from ignored_messages
    """
    def __init__(self, log, ignored_messages=tuple()):
        self._log = log
        # self._ignored = ignored_messages

    def write(self, message):
        self._log(message)

    def flush(self):
        pass


@contextlib.contextmanager
def _spawn(command, timeout=None):
    # log command
    logging.info(termcolor.colored(command, attrs=["bold"]))

    # spawn command
    child = pexpect.spawn(
        command,
        encoding="utf-8",
        cwd=os.getcwd(),
        env=dict(os.environ),
        ignore_sighup=True,
        timeout=timeout)

    try:
        # log command output, ignore any messages containing anything from stdin
        child.logfile_read = _StreamToLogger(logging.info)
        yield child
    finally:
        child.close()



def _run(command, timeout=None):
    """ Run a command, returns command output """

    with _spawn(command, timeout) as child:
        command_output = child.read().strip()

    if child.signalstatus is None and child.exitstatus != 0:
        logging.info("{} exited with {}".format(shlex.quote(command), child.exitstatus))
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
            raise ConnectionError(_("Could not connect to GitHub."))
    return r.content

def _merge_config(local, root):
    """
    Merge local (tool specific part of .cs50.yaml at problem in repo)
    with root (tool specific part of .cs50.yaml at root of repo)
    """
    result = copy.deepcopy(root)

    for key in local:
        if key in root and isinstance(root[key], list):
            # Note: References in .yaml become actual Python references once parsed
            # Cannot use += here!
            result[key] = result[key] + local[key]
        else:
            result[key] = local[key]
    return result

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

def _create_exclude(config):
    """
    Create a git exclude file from include + required key as per the tool's yaml entry in .cs50.yaml
        if no include key is given, all keys are included (exclude is empty)
    Includes are globbed and matched files are explicitly added to the exclude file
    """
    if "include" not in config:
        return ""

    includes = []
    for include in config["include"]:
        includes += glob.glob(include)

    if "required" in config:
        includes += [req for req in config["required"] if req not in includes]

    return "*\n" + "\n".join(f"!{i}" for i in includes)

def _add_with_lfs(files, git):
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
    i = child.expect(["Hi (.+)! You've successfully authenticated", "Enter passphrase for key", "Permission denied", "Are you sure you want to continue connecting"])
    child.close()
    if i == 0:
        username = child.match.groups()[0]
        return User(name=username,
                   password=None,
                   repo=f"git@github.com/{org}/{username}")

@contextlib.contextmanager
def _authenticate_https(org):
    """ Try authenticating via HTTPS, if succesful yields User, otherwise raises Error """
    cache = Path("~/.git-credential-cache").expanduser()
    cache.mkdir(mode=0o700, exist_ok=True)
    socket = cache / "push50"

    try:
        cmd = f"git -c credential.helper='cache --socket {socket}' credential fill"
        logging.info(termcolor.colored(cmd, attrs=["bold"]))
        child = pexpect.spawn(cmd, encoding="utf8")
        child.logfile_read = _StreamToLogger(logging.info)
        child.sendline("")

        i = child.expect(["Username:", "Password:", "username=([^\r]+)\r\npassword=([^\r]+)"])
        if i == 2:
            username, password = child.match.groups()
        else:
            username = password = None
        child.close()

        if not password:
            username = _get_username("Github username: ")
            password = _get_password("Github password: ")

        res = requests.get("https://api.github.com/user", auth=(username, password))

        # check for 2-factor authentication http://github3.readthedocs.io/en/develop/examples/oauth.html?highlight=token
        if "X-GitHub-OTP" in res.headers:
            raise Error("Looks like you have two-factor authentication enabled!"
                        " Please generate a personal access token and use it as your password."
                        " See https://help.github.com/articles/creating-a-personal-access-token-for-the-command-line for more info.")

        if res.status_code != 200:
            logging.info(res.headers)
            logging.info(res.text)
            raise Error("Invalid username and/or password." if res.status_code == 401 else "Could not authenticate user.")

        # canonicalize (capitalization of) username,
        # especially if user logged in via email address
        username = res.json()["login"]

        timeout = int(datetime.timedelta(weeks=1).total_seconds())

        with _spawn(f"git -c credential.helper='cache --socket {socket} --timeout {timeout}' "
                         "-c credentialcache.ignoresighub=true "
                         "credential approve") as child:
            child.sendline(f"username={username}")
            child.sendline(f"password={password}")
            child.sendline("")


        yield User(name=username,
                   password=password,
                   repo=f"https://{username}@github.com/{org}/{username}")
    except:
        _run(f"git credential-cache --socket {socket} exit")
        try:
            with _spawn("git credential-osxkeychain erase") as child:
                child.sendline("host=github.com")
                child.sendline("protocol=https")
        except Error:
            pass
        raise

@contextlib.contextmanager
def _file_buffer(contents):
    """ Contextmanager that produces a temporary file with contents """
    with tempfile.TemporaryFile("r+") as f:
        f.writelines(contents)
        f.seek(0)
        yield f

def _get_username(prompt="Username: "):
    """ Prompt the user for username """
    try:
        return input(prompt).strip()
    except EOFError:
        print()

def _get_password(prompt="Password: "):
    """ Prompt the user for password """
    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    tty.setraw(fd)

    print(prompt, end="", flush=True)
    password = []
    try:
        while True:
            ch = sys.stdin.buffer.read(1)[0]
            if ch in (ord("\r"), ord("\n"), 4): # if user presses Enter or ctrl-d
                print("\r")
                break
            elif ch == 127: # DEL
                try:
                    password.pop()
                except IndexError:
                    pass
                else:
                    print("\b \b", end="", flush=True)
            elif ch == 3: # ctrl-c
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
    push("submit50", "cs50/problems2/foo/hello", "submit50")

    #LOCAL_PATH = "./test"
    #print(local("cs50/problems2/master/hello", "check50"))
    pass
