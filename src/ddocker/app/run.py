"""
"""

import logging
from ddocker.app import subcommand


logger = logging.getLogger("ddocker.build")


def args(parser):
    pass


@subcommand("run", callback=args)
def main(args):
    print "run", args
