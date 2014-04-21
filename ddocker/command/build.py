"""
"""

from ddocker import subcommand


def args(parser):
    pass


@subcommand("build", callback=args)
def main(args):
    print "build", args
