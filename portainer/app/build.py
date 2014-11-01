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
    parser.add_argument("--executor-uri", dest="executor", required=True,
                        help="URI to the portainer executor for mesos")

    # Build Arguments
    group = parser.add_argument_group("build")
    group.add_argument("--build-cpu", default=2.0,
                       help="CPU allocated to building the images")
    group.add_argument("--build-mem", default=1024,
                       help="Memory allocated to building the image (mb)")
    group.add_argument("--repository", required=False,
                       help="Repository name for the docker image (e.g foo/bar)")
    group.add_argument("--from", required=False, dest="pull_registry",
                       help="Docker registry to pull images FROM")
    group.add_argument("--to", required=True, dest="push_registry",
                       help="Docker registry to push built images TO")
    group.add_argument("--stream", default=False, action="store_true",
                       help="Stream the docker build output to the framework")
    group.add_argument("--tag", action="append", default=[], dest="tags",
                       help="Multiple tags to apply to the image once built")
    group.add_argument("--container-image", default="jpetazzo/dind",
                       help="Docker image to run the portainer executor in")
    group.add_argument("--insecure", default=False, action="store_true",
                       help="Enable pulling/pushing of images with insecure registries")

    # Arguments for the staging filesystem
    group = parser.add_argument_group("fs")
    group.add_argument("--staging-uri", required=False,
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

    if args.docker_host:
        args.container_image = None

    scheduler = Scheduler(
        tasks=[(d, args.tags) for d in args.dockerfile],
        executor_uri=args.executor,
        cpu_limit=args.build_cpu,
        mem_limit=args.build_mem,
        repository=args.repository,
        pull_registry=args.pull_registry,
        push_registry=args.push_registry,
        staging_uri=args.staging_uri,
        container_image=args.container_image,
        stream=args.stream,
        docker_host=args.docker_host,
        verbose=args.verbose,
        insecure_registries=args.insecure
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

    # Check to see if any of the tasks failed
    if scheduler.failed > 0:
        logger.error("%d images failed to build", scheduler.failed)
        sys.exit(1)
    else:
        logger.error("Successfully built %d images", scheduler.finished)
        sys.exit(0)
