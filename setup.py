
from setuptools import setup

install_requires = ["attrs>=18.1,<20", "pexpect>=4.6,<5", "pyyaml>=3.10,<6", "requests>=2.13,<3", "termcolor>=1.1,<2", "jellyfish>=0.7,<1", "cryptography>=2.7"]

if __import__("os").name == "nt":
    install_requires.append("pywinpty>=0.5")

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
    install_requires=install_requires,
    keywords=["lib50"],
    name="lib50",
    python_requires=">= 3.6",
    packages=["lib50"],
    url="https://github.com/cs50/lib50",
    version="2.0.0",
    include_package_data=True
)
