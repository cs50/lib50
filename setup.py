from setuptools import setup
from setuptools.command.build_py import build_py

import os
import glob

try:
    from babel.messages import frontend as babel
except ImportError:
    cmdclass = {}
else:
    # https://stackoverflow.com/questions/40051076/babel-compile-translation-files-when-calling-setup-py-install
    class InstallWithCompile(build_py):
        def run(self):
            compiler = babel.compile_catalog(self.distribution)
            option_dict = self.distribution.get_option_dict("compile_catalog")
            compiler.domain = [option_dict["domain"][1]]
            compiler.directory = option_dict["directory"][1]
            compiler.run()
            # os.system("tree")
            # self.mo_files = glob.glob("**.mo", recursive=True)
            # print(self.mo_files)
            super().run()
    cmdclass = {
        "build_py": InstallWithCompile
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
    license="GPLv3",
    description="This is push50, CS50's internal library for using GitHub as data storage.",
    install_requires=["attrs", "babel", "pexpect", "pyyaml", "requests", "termcolor"],
    keywords=["push50"],
    name="push50",
    python_requires=">= 3.6",
    packages=["push50"],
    url="https://github.com/cs50/push50",
    version="1.0.0",
    package_data={'': ['locale/*/*/*.mo', 'locale/*/*/*.po']},
    include_package_data=True
)
