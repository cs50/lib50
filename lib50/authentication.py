import attr
import contextlib
import enum
import os
import pexpect
import re
import sys
import termcolor
import termios
import tty

from pathlib import Path

from . import _
from . import _api as api
from ._errors import ConnectionError, InvalidBranchError, RejectedHonestyPromptError

__all__ = ["User", "authenticate", "logout"]

_CREDENTIAL_SOCKET = Path("~/.git-credential-cache/lib50").expanduser()


@attr.s(slots=True)
class User:
    """An authenticated GitHub user that has write access to org/repo."""
    name = attr.ib()
    repo = attr.ib()
    org = attr.ib()
    passphrase = attr.ib(default=str)
    email = attr.ib(default=attr.Factory(lambda self: f"{self.name}@users.noreply.github.com",
                                         takes_self=True),
                    init=False)

@contextlib.contextmanager
def authenticate(org, repo=None, auth_method=None):
    """
    A contextmanager that authenticates a user with GitHub.

    :param org: GitHub organisation to authenticate with
    :type org: str
    :param repo: GitHub repo (part of the org) to authenticate with. Default is the user's GitHub login.
    :type repo: str, optional
    :param auth_method: The authentication method to use.  Accepts `"https"` or `"ssh"`. \
                        If any other value is provided, attempts SSH \
                        authentication first and fall back to HTTPS if SSH fails.
    :type auth_method: str, optional
    :return: an authenticated user
    :type: lib50.User

    Example usage::

        from lib50 import authenticate

        with authenticate("me50") as user:
            print(user.name)

    """
    def try_https(org, repo):
        with _authenticate_https(org, repo=repo) as user:
            return user

    def try_ssh(org, repo):
        user = _authenticate_ssh(org, repo=repo)
        if user is None:
            raise ConnectionError
        return user

    # Showcase the type of authentication based on input
    method_label = f" ({auth_method.upper()})" if auth_method in ("https", "ssh") else ""
    with api.ProgressBar(_("Authenticating{}").format(method_label)) as progress_bar:
        # Both authentication methods can require user input, best stop the bar
        progress_bar.stop()

        match auth_method:
            case "https":
                yield try_https(org, repo)
            case "ssh":
                yield try_ssh(org, repo)
            case _:
                # Try auth through SSH
                try:
                    yield try_ssh(org, repo)
                except ConnectionError:
                    # SSH auth failed, fallback to HTTPS
                    yield try_https(org, repo)

def logout():
    """
    Log out from git.

    :return: None
    :type: None
    """
    api.run(f"git credential-cache --socket {_CREDENTIAL_SOCKET} exit")


def run_authenticated(user, command, quiet=False, timeout=None):
    """Run a command as a authenticated user. Returns command output."""
    try:
        with api.spawn(command, quiet, timeout) as child:
            match = child.expect([
                "Enter passphrase for key",
                "Password for",
                "cannot lock ref",
                pexpect.EOF
            ])

            # In case  "Enter passphrase for key" appears, send user's passphrase
            if match == 0:
                child.sendline(user.passphrase)
                pass
            # In case "Password for" appears, https authentication failed
            elif match == 1:
                raise ConnectionError
            # In case "cannot lock ref" appears, a conflict with an existing branch prefix
            elif match == 2:
                # Get the full output by reading until EOF
                full_output = child.before + child.after + child.read()
                command_output = full_output.strip().replace("\r\n", "\n")

                # Try to extract the conflicting branch prefix from the error message
                # Pattern: 'refs/heads/cs50/problems/2025/x' exists
                branch_prefix_match = re.search(r"'refs/heads/([^']+)' exists", command_output)
                
                if branch_prefix_match:
                    conflicting_prefix = branch_prefix_match.group(1)
                    error_msg = _("Looks like you're trying to push to a branch that conflicts with an existing one in the repository.\n"
                                  f"The branch prefix '{conflicting_prefix}' already exists.\n"
                                  f"You can view the existing branches at {user.repo}/branches"
                                  )
                else:
                    error_msg = _("You are trying to push to a branch that is not allowed.\n"
                                  f"You can view the existing branches at {user.repo}/branches"
                                  )

                raise InvalidBranchError(error_msg)

            command_output = child.read().strip().replace("\r\n", "\n")

    except pexpect.TIMEOUT:
        api.logger.info(f"command {command} timed out")
        raise TimeoutError(timeout)

    return command_output


def _authenticate_ssh(org, repo=None):
    """Try authenticating via ssh, if succesful yields a User, otherwise raises Error."""

    class State(enum.Enum):
        FAIL = 0
        SUCCESS = 1
        PASSPHRASE_PROMPT = 2
        NEW_KEY = 3

    # Require ssh-agent
    child = pexpect.spawn("ssh -p443 -T git@ssh.github.com", encoding="utf8")

    # GitHub prints 'Hi {username}!...' when attempting to get shell access
    try:
        state = State(child.expect([
            "Permission denied",
            "Hi (.+)! You've successfully authenticated",
            "Enter passphrase for key",
            "Are you sure you want to continue connecting"
        ]))
    except (pexpect.EOF, pexpect.TIMEOUT):
        return None

    passphrase = ""

    try:
        # New SSH connection
        if state == State.NEW_KEY:
            # yes to Continue connecting
            child.sendline("yes")

            state = State(child.expect([
                "Permission denied",
                "Hi (.+)! You've successfully authenticated",
                "Enter passphrase for key"
            ]))

        # while passphrase is needed, prompt and enter
        while state == State.PASSPHRASE_PROMPT:

            # Prompt passphrase
            passphrase = _prompt_password("Enter passphrase for SSH key: ")

            # Enter passphrase
            child.sendline(passphrase)

            state = State(child.expect([
                "Permission denied",
                "Hi (.+)! You've successfully authenticated",
                "Enter passphrase for key"
            ]))

            # In case of a re-prompt, warn the user
            if state == State.PASSPHRASE_PROMPT:
                print("Looks like that passphrase is incorrect, please try again.")

            # In case of failed auth and no re-prompt, warn user and fall back on https
            if state == State.FAIL:
                print("Looks like that passphrase is incorrect, trying authentication with"\
                    " username and Personal Access Token instead.")

        # Succesfull authentication, done
        if state == State.SUCCESS:
            username = child.match.groups()[0]
        # Failed authentication, nothing to be done
        else:
            if not os.environ.get("CODESPACES"):
                _show_gh_changes_warning()
                
            return None
    finally:
        child.close()

    return User(name=username,
                repo=f"ssh://git@ssh.github.com:443/{org}/{username if repo is None else repo}",
                org=org,
                passphrase=passphrase)


@contextlib.contextmanager
def _authenticate_https(org, repo=None):
    """Try authenticating via HTTPS, if succesful yields User, otherwise raises Error."""
    _CREDENTIAL_SOCKET.parent.mkdir(mode=0o700, exist_ok=True)
    api.Git.cache = f"-c credential.helper= -c credential.helper='cache --socket {_CREDENTIAL_SOCKET}'"
    git = api.Git().set(api.Git.cache)

    # Get username/PAT from environment variables if possible
    username = os.environ.get("CS50_GH_USER")
    password = os.environ.get("CS50_TOKEN")

    # If in codespaces, check for missing environment variables and prompt user to re-login
    if os.environ.get("CODESPACES"):
        missing_env_vars = False
        for env_var in ("CS50_GH_USER", "CS50_TOKEN"):
            if os.environ.get(env_var) is None:
                missing_env_vars = True
                error = f"Missing environment variable {env_var}"
                print(termcolor.colored(error, color="red", attrs=["bold"]))
        if missing_env_vars:
            prompt = "Please visit https://cs50.dev/restart to restart your codespace."
            print(termcolor.colored(prompt, color="yellow", attrs=["bold"]))
            logout()
            sys.exit(1)

    # Otherwise, get credentials from cache if possible
    if username is None or password is None:
        try:
            with api.spawn(git("credential fill"), quiet=True) as child:
                child.sendline("protocol=https")
                child.sendline("host=github.com")
                child.sendline("")
                i = child.expect([
                    "Username for '.+'",
                    "Password for '.+'",
                    "username=([^\r]+)\r\npassword=([^\r]+)\r\n"
                ])
                if i == 2:
                    cached_username, cached_password = child.match.groups()

                    # if cached credentials differ from existing env variables, don't use cache
                    same_username = username is None or username == cached_username
                    same_password = password is None or password == cached_password
                    if same_username and same_password:
                        username, password = cached_username, cached_password
                else:
                    child.close()
                    child.exitstatus = 0
        except pexpect.exceptions.EOF as e:
            pass

    # Prompt for username if not in env vars or cache
    if username is None:
        if not os.environ.get("CODESPACES"):
            _show_gh_changes_warning()

        username = _prompt_username(_("Enter username for GitHub: "))

    # Prompt for PAT if not in env vars or cache
    if password is None:
        if not os.environ.get("CODESPACES"):
            _show_gh_changes_warning()

        password = _prompt_password(_("Enter personal access token for GitHub: "))

    try:
        # Credentials are correct, best cache them
        with api.spawn(git("-c credentialcache.ignoresighup=true credential approve"), quiet=True) as child:
            child.sendline("protocol=https")
            child.sendline("host=github.com")
            child.sendline(f"path={org}/{username}")
            child.sendline(f"username={username}")
            child.sendline(f"password={password}")
            child.sendline("")

        yield User(name=username,
                   repo=f"https://{username}@github.com/{org}/{username if repo is None else repo}",
                   org=org)
    except Exception as e:

        # Do not prompt message if user rejects the honesty prompt
        if not isinstance(e, RejectedHonestyPromptError) and not isinstance(e, InvalidBranchError):
            msg = _("You might be using your GitHub password to log in," \
            " but that's no longer possible. But you can still use" \
            " check50 and submit50! See https://cs50.readthedocs.io/github for instructions.")
            print(termcolor.colored(msg, color="yellow", attrs=["bold"]))

        # Some error occured while this context manager is active, best forget credentials.
        logout()
        raise
    except BaseException:
        # Some special error (like SIGINT) occured while this context manager is active, best forget credentials.
        logout()
        raise


def _show_gh_changes_warning():
    """Only once show a warning on the no password change at GitHub."""
    if not hasattr(_show_gh_changes_warning, "showed"):
        warning = "GitHub now requires that you use SSH or a personal access token"\
                        " instead of a password to log in, but you can still use check50 and submit50!"\
                        " See https://cs50.readthedocs.io/github for instructions if you haven't already!"
        print(termcolor.colored(warning, color="yellow", attrs=["bold"]))
    _show_gh_changes_warning.showed = True


def _prompt_username(prompt="Username: "):
    """Prompt the user for username."""
    try:
        while True:
            username = input(prompt).strip()
            if not username:
                print("Username cannot be empty, please try again.")
            elif "@" in username:
                print("Please enter your GitHub username, not email.")
            else:
                return username
    except EOFError:
        print()


def _prompt_password(prompt="Password: "):
    """Prompt the user for password, printing asterisks for each character"""
    print(prompt, end="", flush=True)
    password_bytes = []
    password_string = ""

    with _no_echo_stdin():
        while True:
            # Read one byte
            ch = sys.stdin.buffer.read(1)[0]
            # If user presses Enter or ctrl-d
            if ch in (ord("\r"), ord("\n"), 4):
                print("\r")
                break
            # Del
            elif ch == 127:
                if len(password_string) > 0:
                    print("\b \b", end="", flush=True)
                # Remove last char and its corresponding bytes
                password_string = password_string[:-1]
                password_bytes = list(password_string.encode("utf8"))
            # Ctrl-c
            elif ch == 3:
                print("^C", end="", flush=True)
                raise KeyboardInterrupt
            else:
                password_bytes.append(ch)

                # If byte added concludes a utf8 char, print *
                try:
                    password_string = bytes(password_bytes).decode("utf8")
                except UnicodeDecodeError:
                    pass
                else:
                    print("*", end="", flush=True)

    if not password_string:
        print("Password cannot be empty, please try again.")
        return _prompt_password(prompt)

    return password_string


@contextlib.contextmanager
def _no_echo_stdin():
    """
    On Unix only, have stdin not echo input.
    https://stackoverflow.com/questions/510357/python-read-a-single-character-from-the-user
    """
    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    tty.setraw(fd)
    try:
        yield
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
