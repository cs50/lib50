import collections
import contextlib
import copy
import datetime
import gettext
import itertools
import logging
import os
from pathlib import Path
import pkg_resources
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import termios
import time
import tty
import glob
import requests
import pexpect
from git import Git, GitError, Repo, SymbolicReference
import yaml

#Git.GIT_PYTHON_TRACE = 1
#logging.basicConfig(level="INFO")

# Internationalization
gettext.install("messages", pkg_resources.resource_filename("push50", "locale"))


def push(org, branch, tool, prompt = (lambda included, excluded : True)):
    """ Push to github.com/org/repo=username/branch if tool exists """
    check_dependencies()

    tool_yaml = connect(org, branch, tool)

    with authenticate(org) as user:
        with prepare(org, branch, user, tool_yaml) as repository:
            if prompt(repository.included, repository.excluded):
                upload(repository, branch)

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
def authenticate(org):
    """
    Authenticate with GitHub via SSH if possible
    Otherwise authenticate via HTTPS
    returns: an authenticated User
    """
    with ProgressBar("Authenticating") as progress_bar:
        # try authentication via SSH
        try:
            with _authenticate_ssh(org) as user:
                yield user
        except Error:
            # else, authenticate via https, caching credentials
            progress_bar.stop()
            with _authenticate_https(org) as user:
                yield user

@contextlib.contextmanager
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
        git = lambda : Git()(git_dir=git_dir, work_tree=os.getcwd())

        # clone just .git folder
        try:
            git().clone(user.repo, git_dir, bare=True)
        except GitError:
            if user.password:
                e = Error(_("Looks like {} isn't enabled for your account yet. "
                            "Go to https://cs50.me/authorize and make sure you accept any pending invitations!".format(org)))
            else:
                e = Error(_("Looks like you have the wrong username in ~/.gitconfig or {} isn't yet enabled for your account. "
                            "Double-check ~/.gitconfig and then log into https://cs50.me/ in a browser, "
                            "click \"Authorize application\" if prompted, and re-run {} here.".format(org, org)))
            raise e

        # TODO .gitattribute stuff

        # set user name/email in repo config
        repo = Repo(git_dir)
        config = repo.config_writer()
        config.set_value("user", "email", user.email)
        config.set_value("user", "name", user.name)

        # switch to branch without checkout
        git().symbolic_ref("HEAD", f"refs/heads/{branch}")

        # add exclude file
        exclude = _convert_yaml_to_exclude(tool_yaml)
        exclude_path = f"{git_dir}/info/exclude"
        with open(exclude_path, "w") as f:
            f.write(exclude + "\n")
            f.write(".git*\n")
            f.write(".lfs*\n")
        config.set_value("core", "excludesFile", exclude_path)
        config.release()

        # add files to staging area
        git().add(all=True)

        # get file lists
        files = git().ls_files().split("\n")
        excluded_files = git().ls_files(other=True).split("\n")

        # TODO git lfs

        # check that at least 1 file is staged
        if not files:
            raise Error(_("No files in this directory are expected for submission."))

        progress_bar.stop()
        yield Repository(git, files, excluded_files)

def upload(repository, branch):
    """ Commit + push to branch """
    with ProgressBar("Uploading"):
        # decide on commit name
        headers = requests.get("https://api.github.com/").headers
        commit_name = datetime.datetime.strptime(headers["Date"], "%a, %d %b %Y %H:%M:%S %Z")
        commit_name = commit_name.strftime("%Y%m%dT%H%M%SZ")

        # commit + push
        repository.git().commit(message=commit_name, allow_empty=True)
        repository.git().push("origin", branch)

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

class InvalidSlug(Error):
    pass

User = collections.namedtuple("User", ["name", "password", "email", "repo"])
Repository = collections.namedtuple("Repository", ["git", "included", "excluded"])

class ProgressBar:
    """ Show a progress bar starting with message """
    def __init__(self, message):
        self._message = message
        self._progressing = True
        self._thread = None

    def stop(self):
        """Stop the progress bar"""
        if self._progressing:
            self._progressing = False
            self._thread.join()

    def __enter__(self):
        def progress_runner():
            print(self._message + "...", end="", flush=True)
            while self._progressing:
                print(".", end="", flush=True)
                time.sleep(0.5)
            print()

        self._thread = threading.Thread(target=progress_runner)
        self._thread.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()

def _parse_slug(slug, offline=False):
    """ parse <org>/<repo>/<branch>/<problem_dir> from slug """
    git = Git()

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
                                for line in git.ls_remote(f"https://github.com/{org}/{repo}", heads=True).split("\n"))
            else:
                branches = map(str, Repo(f"~/.local/share/push50/{org}/{repo}").branches)
        except GitError:
            raise InvalidSlug(slug)

        for branch in branches:
            if remainder.startswith(f"{branch}/"):
                return branch, remainder[len(branch)+1:]
        else:
            raise InvalidSlug(slug)

    branch, problem = parse_branch(offline)

    return org, repo, branch, Path(problem)

def _get_content_from(org, repo, branch, filepath):
    """ Get all content from org/repo/branch/filepath at GitHub """
    url = "https://github.com/{}/{}/raw/{}/{}".format(org, repo, branch, filepath)
    r = requests.get(url)
    if not r.ok:
        raise Error(_("Invalid slug. Did you mean to submit something else?"))
    return r.content

def _merge_cs50_yaml(cs50, root_cs50):
    """ Merge .cs50.yaml with .cs50.yaml from root of repo """
    result = copy.deepcopy(root_cs50)

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

@contextlib.contextmanager
def _authenticate_ssh(org):
    """ Try authenticating via ssh, if succesful yields a User, otherwise raises Error """
    # require ssh-agent
    child = pexpect.spawn("ssh git@github.com", encoding="utf8")
    # github prints 'Hi {username}!...' when attempting to get shell access
    i = child.expect(["Hi (.+)! You've successfully authenticated", "Enter passphrase for key", "Permission denied", "Are you sure you want to continue connecting"])
    child.close()
    if i == 0:
        username = child.match.groups()[0]
        yield User(name=username,
                   password=None,
                   email=f"{username}@users.noreply.github.com",
                   repo=f"git@github.com/{org}/{username}")
    else:
        raise Error("Could not authenticate over SSH")

@contextlib.contextmanager
def _authenticate_https(org):
    """ Try authenticating via HTTPS, if succesful yields User, otherwise raises Error """
    git = Git()

    cache = Path("~/.git-credential-cache").expanduser()
    cache.mkdir(mode=0o700, exist_ok=True)
    socket = cache / "push50"

    try:
        child = pexpect.spawn(f"git -c credential.helper='cache --socket {socket}' credential fill", encoding="utf8")
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
            logging.debug(res.headers)
            logging.debug(res.text)
            raise Error("Invalid username and/or password." if res.status_code == 401 else "Could not authenticate user.")

        # canonicalize (capitalization of) username,
        # especially if user logged in via email address
        username = res.json()["login"]

        timeout = int(datetime.timedelta(weeks=1).total_seconds())

        with _file_buffer([f"username={username}", f"password={password}"]) as f:
            git(c=["credential.helper='cache --socket {socket} --timeout {timeout}",
                   "credentialcache.ignoresighub=true"]).credential("approve", istream=f)

        yield User(name=username,
                   password=password,
                   email=f"{username}@users.noreply.github.com",
                   repo=f"https://{username}@github.com/{org}/{username}")
    except:
        git.credential_cache(exit, socket=socket)
        try:
            with _file_buffer(["host=github.com", "protocol=https"]) as f:
                git.credential_osxkeychain("erase", istream=f)
        except GitError:
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
    # example check50/submit50 call
    
    def cprint(text="", color=None, on_color=None, attrs=None, **kwargs):
        """Colorizes text (and wraps to terminal's width)."""
        import termcolor
        import textwrap

        columns = 80  # because get_terminal_size's default fallback doesn't work in pipes

        # print text
        termcolor.cprint(textwrap.fill(text, columns, drop_whitespace=False),
                         color=color, on_color=on_color, attrs=attrs, **kwargs)

    # example check50 call
    def prompt(included, excluded):
        if included:
            cprint(_("Files that will be submitted:"), "green")
            for file in included:
                cprint("./{}".format(file), "green")

        # files that won't be submitted
        if excluded:
            cprint(_("Files that won't be submitted:"), "yellow")
            for other in excluded:
                cprint("./{}".format(other), "yellow")

        return True

    push("check50", "cs50/problems2/master/hello", "check50", prompt=prompt)
