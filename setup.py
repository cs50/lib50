from setuptools import find_packages, setup

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
    install_requires=["attrs", "pexpect", "pyyaml", "requests", "termcolor"],
    keywords=["push", "push50"],
    name="push50",
    packages=find_packages(),
    python_requires=">= 3.6",
    py_modules=["push50"],
    url="https://github.com/cs50/push50",
    version="1.0.0"
)
