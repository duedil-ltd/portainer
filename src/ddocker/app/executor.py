"""
"""

import logging
from ddocker.app import subcommand


logger = logging.getLogger("ddocker.executor")


def args(parser):
    pass


@subcommand("build-executor", callback=args)
def main(args):
    print "build-executor", args
    while True:
        pass
