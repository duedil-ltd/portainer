"""
"""

import functools
import logging
import mesos
import os
import sys
import threading

from ddocker.app import subcommand
from ddocker.proto import mesos_pb2
from ddocker.proto import ddocker_pb2


logger = logging.getLogger("ddocker.executor")


def args(parser):
    parser.add_argument("--docker-host",
                        help="Custom docker host to connect to, if this is not "
                             "specified an ephemeral docker daemon will be "
                             "launched by this process.")


@subcommand("build-executor", callback=args)
def main(args):

    executor = Executor()
    driver = mesos.MesosExecutorDriver(executor)

    status = 0
    if driver.run() == mesos_pb2.DRIVER_STOPPED:
        status = 1

    driver.stop()
    sys.exit(status)


class Executor(mesos.Executor):

    TASK_STARTING = mesos_pb2.TASK_STARTING
    TASK_RUNNING = mesos_pb2.TASK_RUNNING
    TASK_FINISHED = mesos_pb2.TASK_FINISHED
    TASK_FAILED = mesos_pb2.TASK_FAILED

    def __init__(self):
        pass

    def registered(self, driver, executorInfo, frameworkInfo, slaveInfo):
        pass

    def disconnected(self, driver):
        pass

    def reregistered(self, driver, slaveInfo):
        pass

    def launchTask(self, driver, taskInfo):

        logger.info("Launched task %s", taskInfo.task_id.value)

        # Parse the build task object
        try:
            buildTask = ddocker_pb2.BuildTask()
            buildTask.ParseFromString(taskInfo.data)
        except Exception, e:
            logger.error("Failed to parse build task data %r", e)
            self._update(driver, taskInfo, self.TASK_FAILED)

        # Tell mesos that we're starting the task
        self._update(driver, taskInfo, self.TASK_STARTING)

        # Spawn another thread to run the task freeing up the executor
        thread = threading.Thread(target=functools.partial(
            self._buildImage,
            driver,
            taskInfo,
            buildTask
        ))

        thread.setDaemon(False)
        thread.start()

    def killTask(self, driver, taskId):
        pass

    def _update(self, driver, taskInfo, state):
        """Send an updated state for a task."""

        logger.info("Sending task update %r for task %s", state, taskInfo.task_id.value)

        update = mesos_pb2.TaskStatus()
        update.task_id.value = taskInfo.task_id.value
        update.state = state
        driver.sendStatusUpdate(update)

    def _buildImage(self, driver, taskInfo, buildTask):
        """Build an image for the given buildTask."""

        self._update(driver, taskInfo, self.TASK_RUNNING)

        try:
            sandbox_dir = os.getcwd()
            context_path = os.path.join(sandbox_dir, buildTask.context)

            image_name = "%s/%s" % (buildTask.image.repository.username, buildTask.image.repository.repo_name)
            logger.info("Building image %s from context %s", image_name, context_path)

            if not os.path.exists(context_path):
                raise Exception("Context %s does not exist" % (context_path))

            self._update(driver, taskInfo, self.TASK_FINISHED)
        except Exception, e:
            logger.error("Caught exception building image: %s", e)
            self._update(driver, taskInfo, self.TASK_FAILED)
