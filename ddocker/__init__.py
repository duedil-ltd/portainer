"""
"""

import argparse

parser = argparse.ArgumentParser(
    prog="ddocker",
    fromfile_prefix_chars="@"
)

subparsers = parser.add_subparsers()


def subcommand(name, callback=None):
    """A decorator for main functions to add themselves as subcommands."""

    def decorator(fn):

        subparser = subparsers.add_parser(name)
        subparser.set_defaults(_fn=fn, _name=name, _parser=subparser)

        if callback:
            callback(subparser)

        return fn

    return decorator
