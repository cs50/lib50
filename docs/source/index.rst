``lib50``
===========

.. toctree::
   :hidden:
   :maxdepth: 3
   :caption: Contents:

   api

.. Indices and tables
.. ==================

.. * :ref:`genindex`
.. * :ref:`api`
.. * :ref:`modindex`
.. * :ref:`search`


lib50 is CS50's library for common functionality shared between its tools. The library is, like most of CS50's projects, open-source, but its intention is to serve as an internal library for CS50's own tools. As such it is our current recommendation to not use lib50 as a dependency of one's own projects.

To promote reuse of functionality across CS50 tools, lib50 is designed to be tool agnostic. lib50 provides just the core functionality, but the semantics of that functionality are left up to the tool. For instance, submit50 adds the notion of a submission to a push to GitHub, whereas it is lib50 that provides the ``push`` function that ultimately handles the workflow with GitHub. Or per another example, lib50 provides the functionality to parse and validate ``.cs50.yml`` configuration files, but each individual tool (check50, submit50 and lab50) specifies their own options and handles their own logic.

When looking for a piece of functionality that exists in other CS50 tools, odds are it lives in lib50. Increasingly so then, does the following apply:

"If it seems useful, it probably already exists in lib50" - Chad Sharp, 2019.


Installation
************

First make sure you have Python 3.6 or higher installed. You can download Python |download_python|.

.. |download_python| raw:: html

   <a href="https://www.python.org/downloads/" target="_blank">here</a>

lib50 has a dependency on git, please make sure to |install_git| if git is not already installed.

.. |install_git| raw:: html

   <a href="https://git-scm.com/book/en/v2/Getting-Started-Installing-Git" target="_blank">install git</a>

To install lib50 under Linux / OS X:

.. code-block:: bash

    pip install lib50

Under Windows, please |install_windows_sub|. Then install lib50 within the subsystem.

.. |install_windows_sub| raw:: html

   <a href="https://docs.microsoft.com/en-us/windows/wsl/install-win10" target="_blank">install the Linux subsystem</a>