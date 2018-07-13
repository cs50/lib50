from setuptools import setup
from setuptools.command.install import install
from babel.messages import frontend as babel

import glob
import os
import subprocess
from pathlib import Path


try:
    from babel.messages import frontend as babel
except ImportError:
    cmdclass = {}
else:
    # https://stackoverflow.com/questions/40051076/babel-compile-translation-files-when-calling-setup-py-install
    class InstallWithCompile(install):
        def run(self):
            compiler = babel.compile_catalog(self.distribution)
            option_dict = self.distribution.get_option_dict("compile_catalog")
            compiler.domain = [option_dict["domain"][1]]
            compiler.directory = option_dict["directory"][1]
            compiler.run()
            super().run()
    cmdclass = {
        "compile_catalog": babel.compile_catalog,
        "extract_messages": babel.extract_messages,
        "init_catalog": babel.init_catalog,
        "update_catalog": babel.update_catalog,
        "install": InstallWithCompile
    }



setup(
    author="CS50",
    author_email="sysadmins@cs50.harvard.edu",
    classifiers=[
        "Intended Audience :: Education",
        "Programming Language :: Python :: 3",
        "Topic :: Education",
        "Topic :: Utilities"
    ],
    cmdclass=cmdclass,
    message_extractors = {
        'push50': [('**.py', 'python', None),],
    },
    description="This is push50, CS50's internal library for using GitHub as data storage.",
    install_requires=["attrs", "babel", "keyring", "pexpect", "pyyaml", "requests", "termcolor"],
    keywords=["push50"],
    name="push50",
    python_requires=">= 3.6",
    packages=["push50"],
    url="https://github.com/cs50/push50",
    version="1.0.0",
    include_package_data=True
)
