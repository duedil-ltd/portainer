
import os.path
import errno


def touch(path, times=None):
    """Mimics the behavior of the `touch` UNIX command line tool, to create
    empty files.
    """

    with open(path):
        os.utime(path, times)


def mkdir_p(path):
    """Mimics the behavior of the `mkdir -p` UNIX command line took, creating
    directories recursively, ignoring them if they already exist.
    """

    try:
        os.makedirs(path)
    except OSError, e:
        if e.errno != errno.EEXIST:
            raise
