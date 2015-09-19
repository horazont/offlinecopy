offlinecopy
###########

``offlinecopy`` is a command-line utility which allows to manage a list of
directories which are synchronized to a target.

Installation
============

Place a symlink to ``offlinecopy`` somewhere in your PATH.

Configuration
=============

``offlinecopy`` searches for a ``config.ini`` in
``$XDG_CONFIG_HOME/offlinecopy``. See ``config.example.ini`` for a documented
example. In ``$XDG_CONFIG_HOME/offlinecopy/targets.xml``, the synchronization
targets will be saved.

Workflow
========

``offlinecopy --help`` gives you an overview of the options. In this section, let:

* ``remote`` be the (ssh) host name of a remote server where the data to
  synchronize with lies.
* ``/data/me`` be the directory on ``remote`` where your data lies.

Add targets
-----------

::

    $ offlinecopy add remote:/data/me/Pictures/ ~/Pictures
    $ offlinecopy add remote:/data/me/Music/ ~/Music
    $ offlinecopy add remote:/data/me/Videos/ ~/Videos
    $ offlinecopy add remote:/data/me/Documents/ ~/Documents

.. note::

   The trailing slash on the source is important! ``offlinecopy`` cannot
   trivially check whether the source is a directory or a file, so it

This added four targets to offlinecopy, which we can verify using ``offlinecopy
status``::

    remote:/data/me/Pictures/ => /home/horazont/Pictures/
      - *
    remote:/data/me/Music/ => /home/horazont/Music/
      - *
    remote:/data/me/Documents/ => /home/horazont/Documents/
      - *
    remote:/data/me/Videos/ => /home/horazont/Videos/
      - *

Fetching data from the remote
-----------------------------

Note the lonely ``- *`` in the above output: This indicates that the targets
are entirely excluded. If we would call ``offlinecopy push`` or ``offlinecopy
revert --all`` now, nothing would happen. We need to include directories and/or
summon data first.

Let us assume that the music is already synchronized, we just want to start to
manage it with offlinecopy. In that case, we use ``offlinecopy include`` to
note that the directory is fully in sync and should be included in
synchronization::

    $ offinecopy include ~/Music

The status listing is updated::

    remote:/data/me/Pictures/ => /home/horazont/Pictures/
      - *
    remote:/data/me/Music/ => /home/horazont/Music/
    remote:/data/me/Documents/ => /home/horazont/Documents/
      - *
    remote:/data/me/Videos/ => /home/horazont/Videos/
      - *

The ``- *`` has vanished, the root of Music is not excluded anymore. Now we
want to include the documents, but at the same time also transfer the files
from the remote::

  $ offlinecopy summon ~/Documents

This will start a rsync transfer and when it’s done successfully mark the
Documents directory as included.

To only fetch a certain TV series from your remote videos folder, you would
use::

  $ offlinecopy summon '~/Videos/Name of the series'

Likewise, this changes the status output::

  remote:/data/me/Videos/ => /home/horazont/Videos/
  + Name of the series
  - *

The ``+`` and ``-`` entries are verbatim rsync filter rules.


Pushing changes to the remote
-----------------------------

To push your changes, including deletions, in all non-excluded target
directories to the remote source, one command does everything::

  $ offlinecopy push

To only synchronize back the documents, you would use::

  $ offlinecopy push ~/Documents


Reverting local changes by retransferring from the remote
---------------------------------------------------------

To revert all local changes, use::

  $ offlinecopy revert --all

This affects **all** targets and will overwrite **all** changes (in directories
not excluded). This is pretty dangerous, which is why you need to say ``--all``
to apply it to all targets at once.

To revert only the videos, you would use::

  $ offlinecopy revert ~/Videos


Removing a target from synchronization
--------------------------------------

To stop synchronizing the music, use::

  $ offlinecopy remove ~/Music

This will discard all state ``offlinecopy`` has about ``~/Music`` and it will
pretend to not know that directory.
