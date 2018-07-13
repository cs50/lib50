from setuptools import setup

import glob
import os
import subprocess

def create_mo_files():
    """Compiles .po files in local/LANG to .mo files and returns them as array of data_files"""
    for prefix in glob.glob("locale/*/LC_MESSAGES/*.po"):
        for _,_,files in os.walk(prefix):
            for file in files:
                po_file = Path(prefix) / po_file
                mo_file = po_file.parent / po_file.stem + ".mo"
                subprocess.call(["msgfmt", "-o", mo_file, po_file])

create_mo_files()

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
    keywords=["push50"],
    name="push50",
    python_requires=">= 3.6",
    packages=["push50"],
    url="https://github.com/cs50/push50",
    version="1.0.0",
    include_package_data=True
)
