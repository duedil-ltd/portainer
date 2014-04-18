"""
"""

import argparse
from ddocker.build import main as command_build
from ddocker.run import main as command_run


def main(argv):

    parser = argparse.ArgumentParser(
        prog="ddocker",
        fromfile_prefix_chars="@"
    )

    parser.add_argument("command", help="Command to run [build,run]")

    # Mesos
    group = parser.add_argument_group("mesos")
    group.add_argument("--mesos-master", default="127.0.0.1:5050",
                       help="Mesos master address")
    group.add_argument("--no-checkpoint", default=True, dest="mesos_checkpoint",
                       action="store_false", help="Disable the framework "
                                                  "checkpoint, this allows you "
                                                  "to re-attach to a running "
                                                  "container or building image "
                                                  "in case of an accidental ^C")
    group.add_argument("--framework-id", default=None,
                       help="Custom framework identifier, defaults to a UUID")

    args = parser.parse_args(argv)

    commands = {
        "build": command_build,
        "run": command_run
    }

    if args.command not in commands:
        raise NotImplementedError("Command %s is not valid" % args.command)

    commands[args.command](args)
