"""
"""

from ddocker import subcommand


def args(parser):
    pass


@subcommand("run", callback=args)
def main(args):
    print "run", args
