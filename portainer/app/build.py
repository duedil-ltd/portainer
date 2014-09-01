"""
"""

import logging
import pesos.scheduler
import sys
import threading
import time

from pesos.vendor.mesos import mesos_pb2
from portainer.app import subcommand
from portainer.app.scheduler import Scheduler

logger = logging.getLogger("portainer.build")


def args(parser):
    parser.add_argument("dockerfile", nargs="+")
    parser.add_argument("--tag", action="append", default=[], dest="tags",
                        help="Multiple tags to apply to the image once built")
    parser.add_argument("--executor-uri", dest="executor", required=True,
                        help="URI to the portainer executor for mesos")

    # Build Arguments
    group = parser.add_argument_group("build")
    group.add_argument("--build-cpu", default=2.0,
                       help="CPU allocated to building the images")
    group.add_argument("--build-mem", default=1024 * 4,
                       help="Memory allocated to building the image (mb)")
    group.add_argument("--registry", required=None,
                       help="Docker registry URL to push images to")
    group.add_argument("--repository", required=None,
                       help="Repository name for the docker image (e.g foo/bar)")
    group.add_argument("--stream", default=False, action="store_true",
                       help="Stream the docker build output to the framework")
    group.add_argument("--variable", nargs=2, action="append", default=[], dest="variables",
                       help="Assign key/value variables to be used in Dockerfiles")

    # Arguments for the staging filesystem
    group = parser.add_argument_group("fs")
    group.add_argument("--staging-uri", required=True,
                       help="The URI to use as a base directory for staging files.")


@subcommand("build", callback=args)
def main(args):

    # Do some sanity checking on the arguments
    if len(args.dockerfile) > 1 and args.repository:
        logger.error("The --repository argument cannot be used when building multiple images")
        sys.exit(1)

    # Launch the mesos framework
    framework = mesos_pb2.FrameworkInfo()
    framework.user = "root"
    framework.name = "portainer"

    if args.framework_id:
        framework.id.value = args.framework_id

    scheduler = Scheduler(
        [(d, args.tags) for d in args.dockerfile],
        args.executor,
        args.build_cpu,
        args.build_mem,
        args.registry,
        args.repository,
        dict([(k.lower(), v) for k, v in args.variables]),
        args
    )

    driver = pesos.scheduler.PesosSchedulerDriver(
        scheduler, framework, args.mesos_master
    )

    # Kick off the pesos scheduler and watch the magic happen
    thread = threading.Thread(target=driver.run)
    thread.setDaemon(True)
    thread.start()

    # Wait here until the tasks are done
    while thread.isAlive():
        time.sleep(0.5)
