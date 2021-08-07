import attr
import contextlib
import enum
import pexpect
import sys
import termcolor
import termios
import tty

from pathlib import Path

from . import _
from . import _api as api
from ._errors import ConnectionError

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
def authenticate(org, repo=None):
    """
    A contextmanager that authenticates a user with GitHub via SSH if possible, otherwise via HTTPS.

    :param org: GitHub organisation to authenticate with
    :type org: str
    :param repo: GitHub repo (part of the org) to authenticate with. Default is the user's GitHub login.
    :type repo: str, optional
    :return: an authenticated user
    :type: lib50.User

    Example usage::

        from lib50 import authenticate

        with authenticate("me50") as user:
            print(user.name)

    """
    with api.ProgressBar(_("Authenticating")) as progress_bar:
        # Both authentication methods can require user input, best stop the bar
        progress_bar.stop()
        
        # Show a quick reminder to check https://cs50.ly/github
        warning = "GitHub now requires that you use SSH or a personal access token"\
                  " instead of a password to log in, but you can still use check50 and submit50!"\
                  " See https://cs50.ly/github for instructions if you haven't already!"
        print(termcolor.colored(warning, color="yellow", attrs=["bold"]))

        # Try auth through SSH
        user = _authenticate_ssh(org, repo=repo)
        
        # SSH auth failed, fallback to HTTPS
        if user is None:
            with _authenticate_https(org, repo=repo) as user:
                yield user
        # yield SSH user
        else:
            yield user


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
                pexpect.EOF
            ])
            
            # In case  "Enter passphrase for key" appears, send user's passphrase
            if match == 0:
                child.sendline(user.passphrase)
                pass
            # In case "Password for" appears, https authentication failed
            elif match == 1:
                raise ConnectionError
            
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
                
                warning = "See https://cs50.ly/github for instructions on"\
                          " the different authentication methods if you haven't already!"
                print(termcolor.colored(warning, color="yellow", attrs=["bold"]))

        # Succesfull authentication, done
        if state == State.SUCCESS:
            username = child.match.groups()[0]
        # Failed authentication, nothing to be done
        else:
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

    # Get credentials from cache if possible
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
            username, password = child.match.groups()
        else:
            username = password = None
            child.close()
            child.exitstatus = 0

    # If password is not in cache, prompt
    if password is None:
        username = _prompt_username(_("Enter username for GitHub: "))
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
    except Exception:
        msg = _("You might be using your GitHub password to log in," \
        " but that's no longer possible. But you can still use" \
        " check50 and submit50! See https://cs50.ly/github for instructions.")
        print(termcolor.colored(msg, color="yellow", attrs=["bold"]))

        # Some error occured while this context manager is active, best forget credentials.
        logout()
        raise
    except BaseException:
        # Some special error (like SIGINT) occured while this context manager is active, best forget credentials.
        logout()
        raise


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