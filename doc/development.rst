==========
Developing
==========

Rocket uses the Canonical's Launchpad_ for project management.  On the Rocket `project page`_ you can:

* `Browse the source`_
* `Submit a bug report`_ or wishlist item.
* `Download the latest version`_

.. _Download the latest version: http://launchpad.net/rocket/+download
.. _Browse the source: http://bazaar.launchpad.net/~tdfarrell/rocket/trunk/files
.. _Submit a bug report: http://bugs.launchpad.net/rocket
.. _Launchpad: http://launchpad.net
.. _project page: http://launchpad.net/rocket

Building
========

Rocket can be built into three distributable forms:

* package - The package is for copying into site-packages for the easiest possible install.  The command for building a package is::

    setup.py build_sdist

* monolithic module - The monolithic module concatenates all of the individual Rocket modules into one file for easy inclusion in another project.  This command is only available after the module has been installed to a location in the system path.  The command for building a package is::

    setup.py build_monolithic

* EGG file - EGG files will be made for the cheeseshop once the naming slot is secured.  The command for building a package is::

    setup.py build_egg

Extending
=========

Rocket can be extended to handle multiple middle-ware applications.  

To do so, create a module in the methods subdirectory.  The module should specify a subclass of the Worker_ class.  The subclass should overload Worker's run_app method.  run_app is passed a single parameter, a Connection instance for the requesting client.  run_app is responsible for reading the complete request from the Connection and writing a complete response.  run_app should leave the connection in a state ready to receive another request.  If the client closes the connection or run_app needs to close a connection, it should set the self.closeConnection property to True and return.  It can optionally raise SocketTimeout to put the Connection in the wait_queue to not occupy a worker thread while waiting for the next request.  The app_info_ parameter passed to Rocket will be available as self.app_info.  app_info_ should be treated as read_only since all Worker_ threads use it.

.. _Worker: design.html#worker
.. _app_info: usage.html#app-info

Submitting Bugs
===============

If you encounter a bug, please fill out a bug report on Launchpad (linked above).  Please include:

* Version of Python used.
* Version of Rocket used.
* Traceback of the issue.
* Invocation code (if relevant)
* HTTP client used to discover the bug

*Note about standards compliance:*  The HTTP 1.1 specification allows for a number of corner-case behaviors that are not regularly used.  Because Rocket seeks to be fast and small, some of these features have been left out on purpose.  However, if you find that there is an implementation detail missing that you require, please fill out a bug report or submit a patch and I'll include it.
