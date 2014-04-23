"""
"""

import logging
import mesos
import os
import threading
import time

from ddocker.app import subcommand
from ddocker.app.scheduler import Scheduler
from ddocker.proto import mesos_pb2
from Queue import Queue

logger = logging.getLogger("ddocker.build")


def args(parser):
    parser.add_argument("dockerfile", action="append")

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
    framework.user = "root"
    framework.name = "ddocker"

    if args.framework_id:
        framework.id.value = args.framework_id

    # Create the executor
    executor = mesos_pb2.ExecutorInfo()
    executor.executor_id.value = "builder"
    executor.command.value = "./%s build-executor" % os.path.basename(args.executor)
    executor.name = "Docker Build Executor"
    executor.source = "ddocker"

    # Configure the mesos executor with the ddocker executor uri
    ddocker_executor = executor.command.uris.add()
    ddocker_executor.value = args.executor
    ddocker_executor.executable = True

    # Kick off the scheduler driver
    scheduler = Scheduler(
        task_queue,
        executor,
        args.cpu_limit,
        args.mem_limit,
        args
    )
    driver = mesos.MesosSchedulerDriver(
        scheduler, framework, args.mesos_master
    )

    # Put the task onto the queue
    for dockerfile in args.dockerfile:
        task_queue.put(dockerfile)

    thread = threading.Thread(target=driver.run)
    thread.setDaemon(True)
    thread.start()

    # Wait here until the tasks are done
    while thread.isAlive():
        time.sleep(0.5)
