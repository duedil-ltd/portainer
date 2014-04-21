"""
"""

from ddocker import parser

# Import all the commands
import ddocker.command.build
import ddocker.command.run


def main(argv):

    # Arguments for mesos
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

    # Arguments for S3/HDFS
    # TODO

    args = parser.parse_args(argv)
    args._fn(args)
