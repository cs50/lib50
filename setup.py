if __import__("os").name == "nt":
    raise RuntimeError("lib50 does not support Windows directly. Instead, you should install the Windows Subsystem for Linux (https://docs.microsoft.com/en-us/windows/wsl/install-win10) and then install lib50 within that.")

from setuptools import setup

setup(
    author="CS50",
    author_email="sysadmins@cs50.harvard.edu",
    classifiers=[
        "Intended Audience :: Education",
        "Programming Language :: Python :: 3",
        "Topic :: Education",
        "Topic :: Utilities"
    ],
    message_extractors = {
        'lib50': [('**.py', 'python', None),],
    },
    license="GPLv3",
    description="This is lib50, CS50's own internal library used in many of its tools.",
    install_requires=["attrs>=18.1,<21", "pexpect>=4.6,<5", "pyyaml>=3.10,<6", "requests>=2.13,<3", "termcolor>=1.1,<2", "jellyfish>=0.7,<1", "cryptography>=2.7"],
    extras_require = {
        "develop": ["sphinx", "sphinx-autobuild", "sphinx_rtd_theme"]
    },
    keywords=["lib50"],
    name="lib50",
    python_requires=">= 3.6",
    packages=["lib50"],
    url="https://github.com/cs50/lib50",
    version="3.0.1",
    include_package_data=True
)
