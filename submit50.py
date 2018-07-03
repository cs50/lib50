import push50
import requests
from pkg_resources import get_distribution, parse_version

class Error(Exception):
    pass

def check_announcements():
    """Check for any announcements from cs50.me, raise Error if so"""
    res = requests.get("https://cs50.me/status/submit50") # TODO change this to submit50.io!
    if res.status_code == 200 and res.text.strip():
        raise Error(res.text.strip())

def check_version():
    """Check that submit50 is the latest version according to submit50.io"""
    # retrieve version info
    res = requests.get("https://cs50.me/versions/submit50") # TODO change this to submit50.io!
    if res.status_code != 200:
        raise Error(_("You have an unknown version of submit50. "
                      "Email sysadmins@cs50.harvard.edu!"))

    # check that latest version == version installed
    version_required = res.text.strip()
    if parse_version(version_required) > parse_version(get_distribution("submit50").version):
        raise Error(_("You have an old version of submit50. "
                      "Run update50, then re-run {}!".format(org)))

if __name__ == "__main__":
    check_announcements()
    check_version()
    push50.push("submit50", "hello", sentinel=".submit50.yaml")
