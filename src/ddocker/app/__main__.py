"""
"""

import logging
import sys

from ddocker.app import parser

# Import all the commands
import ddocker.app.build
import ddocker.app.run


def main(argv):

    # Arguments for mesos
    group = parser.add_argument_group("mesos")
    group.add_argument("--verbose", "-v", default=False, action="store_true", dest="verbose",
                       help="Enable verbose logging")
    group.add_argument("--mesos-master", default="127.0.0.1:5050",
                       help="Mesos master address")
    group.add_argument("--checkpoint", default="/tmp/ddocker.checkpoint",
                       help="File path to store the ddocker checkpoint in. The"
                            "checkpoint allows you to re-connect to a building"
                            "image or running container in case of ^C")
    group.add_argument("--no-checkpoint", dest="checkpoint", action="store_false",
                       help="Disable the framework checkpoint file")
    group.add_argument("--framework-id", default=None,
                       help="Custom framework identifier, defaults to a UUID")

    args = parser.parse_args(argv)

    # Configure the logging verbosity/handlers
    handler = logging.StreamHandler(stream=sys.stderr)
    formatter = logging.Formatter(fmt="%(asctime)s[%(name)s] %(message)s")
    handler.setFormatter(formatter)

    for logger in ("ddocker.build", "ddocker.run"):
        logger = logging.getLogger(logger)
        logger.addHandler(handler)
        logger.setLevel(
            logging.DEBUG if args.verbose else logging.INFO
        )

    args._fn(args)

if __name__ == "__main__":
    main(sys.argv[1:])
