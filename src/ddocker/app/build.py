"""
"""

import logging
import pesos.scheduler
import os
import threading
import time

from pesos.vendor.mesos import mesos_pb2
from ddocker.app import subcommand
from ddocker.app.scheduler import Scheduler
from Queue import Queue

logger = logging.getLogger("ddocker.build")


def args(parser):
    parser.add_argument("dockerfile")
    parser.add_argument("--tag", action="append", default=[], dest="tags",
                        help="Multiple tags to apply to the image once built")
    parser.add_argument("--executor-uri", dest="executor", required=True,
                        help="URI to the ddocker executor for mesos")

    # Isolation
    group = parser.add_argument_group("isolation")
    group.add_argument("--cpu-limit", default=1.0,
                       help="CPU allocated to building the image")
    group.add_argument("--mem-limit", default=256,
                       help="Memory allocated to building the image (mb)")

    # Arguments for the staging filesystem
    group = parser.add_argument_group("fs")
    group.add_argument("--staging-uri", default="/tmp/ddocker",
                       help="The URI to use as a base directory for staging files.")
    group.add_argument("--aws-access-key-id", default=os.environ.get("AWS_ACCESS_KEY_ID"),
                       help="Access key for using the S3 filesystem")
    group.add_argument("--aws-secret-access-key", default=os.environ.get("AWS_SECRET_ACCESS_KEY"),
                       help="Secret key for using the S3 filesystem")


@subcommand("build", callback=args)
def main(args):

    logger.info("Building docker image from %s", args.dockerfile)

    task_queue = Queue()

    # Launch the mesos framework
    framework = mesos_pb2.FrameworkInfo()
    framework.user = ""  # Let mesos fill this in
    framework.name = "ddocker"

    if args.framework_id:
        framework.id.value = args.framework_id

    # Kick off the scheduler driver
    scheduler = Scheduler(
        task_queue,
        args.executor,
        args.cpu_limit,
        args.mem_limit,
        args
    )

    driver = pesos.scheduler.MesosSchedulerDriver(
        scheduler, framework, args.mesos_master
    )

    # Put the task onto the queue
    task_queue.put((args.dockerfile, args.tags))

    thread = threading.Thread(target=driver.run)
    thread.setDaemon(True)
    thread.start()

    # Wait here until the tasks are done
    while thread.isAlive():
        time.sleep(0.5)
