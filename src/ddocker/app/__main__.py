"""
"""

import logging
import sys

from ddocker.app import parser

# Import all the commands
import ddocker.app.build
import ddocker.app.executor


def main(argv):

    parser.prog = "ddocker"

    # Arguments for mesos
    group = parser.add_argument_group("mesos")
    group.add_argument("--verbose", "-v", default=False, action="store_true", dest="verbose",
                       help="Enable verbose logging")
    group.add_argument("--mesos-master", default="127.0.0.1:5050",
                       help="Mesos master address")
    group.add_argument("--framework-id", default=None,
                       help="Custom framework identifier, defaults to a UUID")
    group.add_argument("--docker-host", default=None,
                       help="Custom host[:port] for the docker daemon, if not "
                            "specified a short-lived docker daemon will be "
                            "launched for you automatically")
    group.add_argument("--docker-args", default=None,
                       help="When launching an ephemeral docker daemon, these "
                            "arguments will be passed to the `docker -d` call")

    args = parser.parse_args(argv)

    # Configure the logging verbosity/handlers
    handler = logging.StreamHandler(stream=sys.stderr)
    formatter = logging.Formatter(fmt="%(asctime)s[%(name)s] %(message)s")
    handler.setFormatter(formatter)

    for logger in ("ddocker.build", "ddocker.scheduler", "ddocker.executor"):
        logger = logging.getLogger(logger)
        logger.addHandler(handler)
        logger.setLevel(
            logging.DEBUG if args.verbose else logging.INFO
        )

    args._fn(args)

if __name__ == "__main__":
    main(sys.argv[1:])
