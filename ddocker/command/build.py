"""
"""

import logging
import mesos
import os
import threading

from Queue import Queue
from ddocker import subcommand
from ddocker.parser import parse_dockerfile
from ddocker.proto import ddocker_pb2
from ddocker.proto import mesos_pb2

logger = logging.getLogger("ddocker.build")


def args(parser):
    parser.add_argument("dockerfile")


@subcommand("build", callback=args)
def main(args):

    logger.info("Building docker image from %s", args.dockerfile)

    task_queue = Queue()

    # Launch the mesos framework
    framework = mesos_pb2.FrameworkInfo()
    framework.user = ""  # Mesos can select the user
    framework.name = "ddocker"
    framework.failover_timeout = 300  # Timeout after 300 seconds

    # Figure out the framework info from an existing checkpoint
    if args.checkpoint and os.path.exists(args.checkpoint):
        with open(args.checkpoint) as cp:
            checkpoint = ddocker_pb2.Checkpoint()
            ddocker_pb2.Checkpoint.ParseFromString(
                checkpoint, cp.read()
            )

            if not checkpoint.frameworkId:
                raise RuntimeError("No framework ID in the checkpoint")

            logger.info("Registering with checkpoint framework ID %s", checkpoint.frameworkId)
            framework.id.value = checkpoint.frameworkId

    # Kick off the scheduler driver
    scheduler = Scheduler(task_queue, args.checkpoint)
    driver = mesos.MesosSchedulerDriver(
        scheduler, framework, args.mesos_master
    )

    thread = threading.Thread(target=driver.run)
    thread.setDaemon(True)
    thread.start()

    # Parse the dockerfile
    dockerfile = parse_dockerfile(args.dockerfile)

    # Generate the dockerfile build context
    context = generate_build_context(dockerfile)

    # Re-write the dockerfile with new ADD paths for local files
    # Bundle up the assets and the new dockerfile into the build context
    # Upload the build context to the shared filesystem
    # Create a mesos task and ship it to the framework
        # Download the tar to the sandbox
        # POST /build (stdin = the tar)
        # Tag and push the image
    # Return and BAM. DONE.

    thread.join(2)


def generate_build_context(dockerfile):
    """Generate and return a compressed tar archive of the build context."""
    print dockerfile.instructions


class Scheduler(mesos.Scheduler):

    def __init__(self, task_queue, checkpoint):
        self.task_queue = task_queue
        self.checkpoint_path = checkpoint

    def registered(self, driver, frameworkId, masterInfo):
        logger.info("Framework registered with ID %s", frameworkId.value)
        self._checkpoint(frameworkId=frameworkId.value)

    def _checkpoint(self, frameworkId=None):
        """Helper method for persisting checkpoint information."""

        if not self.checkpoint_path:
            logger.debug("Skipping checkpoint, not enabled")
            return

        exists = os.path.exists(self.checkpoint_path)
        with open(self.checkpoint_path, "w+b") as cp:
            checkpoint = ddocker_pb2.Checkpoint()
            if exists:
                ddocker_pb2.Checkpoint.ParseFromString(checkpoint, cp.read())
                cp.seek(0)

            if frameworkId:
                checkpoint.frameworkId = frameworkId

            logger.debug("Written checkpoint to %s", self.checkpoint_path)

            cp.write(checkpoint.SerializeToString())
            cp.truncate()
