from setuptools import find_packages, setup

import glob
import os
import subprocess

def create_mo_files():
    """Compiles .po files in local/LANG to .mo files and returns them as array of data_files"""

    mo_files=[]
    for prefix in glob.glob("locale/*/LC_MESSAGES"):
        for _,_,files in os.walk(prefix):
            for file in files:
                if file.endswith(".po"):
                    po_file = os.path.join(prefix, file)
                    mo_file = os.path.splitext(po_file)[0] + ".mo"
                    subprocess.call(["msgfmt", "-o", mo_file, po_file])
                    mo_files.append((os.path.join("push50", prefix), [mo_file]))
    return mo_files

setup(
    author="CS50",
    author_email="sysadmins@cs50.harvard.edu",
    classifiers=[
        "Intended Audience :: Education",
        "Programming Language :: Python :: 3",
        "Topic :: Education",
        "Topic :: Utilities"
    ],
    description="This is push50, CS50's internal library for using GitHub as data storage.",
    install_requires=["attrs", "keyring", "pexpect", "pyyaml", "requests", "termcolor"],
    data_files=create_mo_files(),
    keywords=["push50"],
    name="push50",
    packages=find_packages(),
    python_requires=">= 3.6",
    py_modules=["push50"],
    url="https://github.com/cs50/push50",
    version="1.0.0"
)
