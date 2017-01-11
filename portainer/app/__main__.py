"""
"""

import logging
import sys

from portainer.app import parser

# Import all the commands
import portainer.app.build
import portainer.app.executor


def main(argv):

    parser.prog = "portainer"

    # Arguments for mesos
    group = parser.add_argument_group("mesos")
    group.add_argument("--verbose", "-v", default=False, action="store_true", dest="verbose",
                       help="Enable verbose logging")
    group.add_argument("--mesos-master", default="127.0.0.1:5050",
                       help="Mesos master address")
    group.add_argument("--framework-id", default=None,
                       help="Custom framework identifier, defaults to a UUID")
    group.add_argument("--framework-role", default=None,
                       help="Role name that the framework should attempt to register with")
    group.add_argument("--docker-host", default=None,
                       help="Custom host[:port] for the docker daemon, if not "
                            "specified a short-lived docker daemon will be "
                            "launched for you automatically")

    args = parser.parse_args(argv)

    # Configure the logging verbosity/handlers
    handler = logging.StreamHandler(stream=sys.stderr)
    formatter = logging.Formatter(fmt="%(asctime)s[%(name)s] %(message)s")
    handler.setFormatter(formatter)

    for logger in ("portainer.build", "portainer.scheduler", "portainer.executor", "pesos",
                   "compactor", "tornado"):
        logger = logging.getLogger(logger)
        logger.propagate = False
        logger.addHandler(handler)
        logger.setLevel(
            logging.DEBUG if args.verbose else logging.INFO
        )

    # Suppress some noisy loggers
    for logger in ("compactor", "tornado"):
        logger = logging.getLogger(logger)
        logger.setLevel(
            logging.DEBUG if args.verbose else logging.WARNING
        )

    args._fn(args)

if __name__ == "__main__":
    main(sys.argv[1:])
