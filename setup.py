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
    install_requires=["attrs", "pexpect", "pyyaml", "requests", "termcolor"],
    keywords=["lib50"],
    name="lib50",
    python_requires=">= 3.6",
    packages=["lib50"],
    url="https://github.com/cs50/lib50",
    version="1.0.1",
    include_package_data=True
)
