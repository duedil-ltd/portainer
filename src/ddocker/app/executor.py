"""
"""

import docker
import functools
import json
import logging
import mesos
import os
import sys
import threading
import re

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
        self.build_task = None

        self.docker = None
        self.docker_daemon = threading.Condition()
        self.docker_daemon_up = False

    def registered(self, driver, executorInfo, frameworkInfo, slaveInfo):

        # Parse the build task object
        try:
            build_task = ddocker_pb2.BuildTask()
            build_task.ParseFromString(executorInfo.data)
        except Exception:
            logger.error("Failed to parse BuildTask in ExecutorInfo.data")
            raise

        self.build_task = build_task

        # Launch the docker daemon
        def launch_docker_daemon():
            self.docker_daemon.acquire()

            if self.docker_daemon_up:
                return

            # Launch the subprocess
            # self._fork_docker()
            # Sleep for a second
            import time
            time.sleep(10)
            # Test the REST API

            self.docker = docker.Client()

            self.docker_daemon.notifyAll()
            self.docker_daemon.release()

        if not build_task.HasField("docker_host"):
            daemon_thread = threading.Thread(target=launch_docker_daemon)
            daemon_thread.setDaemon(True)
            daemon_thread.start()
        else:
            host = "http://%s/" % build_task.docker_host
            self.docker = docker.Client(host)

    def disconnected(self, driver):
        pass

    def reregistered(self, driver, slaveInfo):
        pass

    def launchTask(self, driver, taskInfo):

        logger.info("Launched task %s", taskInfo.task_id.value)

        # Tell mesos that we're starting the task
        self._update(driver, taskInfo, self.TASK_STARTING)

        # Spawn another thread to run the task freeing up the executor
        thread = threading.Thread(target=functools.partial(
            self._build_image,
            driver,
            taskInfo,
            self.build_task
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

    def _wrap_docker_stream(self, stream):
        """Wrapper to parse the different types of messages from the
        Docker Remote API and spit them out in a friendly format."""

        for msg in stream:
            logger.info("Received update from docker: %s", msg.rstrip())

            # Parse the message / handle any errors from docker
            try:
                update = json.loads(msg.rstrip())
            except Exception, e:
                logger.error("Caught exception parsing message %s %r", msg, e)
            else:
                if "error" in update:
                    logger.error("Docker error: %s", update["error"])
                    yield update["error"]
                    raise Exception("Docker encountered an error")

                friendly_message = None

                if "stream" in update:
                    friendly_message = update["stream"].rstrip()
                if "status" in update:
                    friendly_message = update["status"].rstrip()
                    if "id" in update:
                        friendly_message = "[%s] %s" % (update["id"], friendly_message)
                    if "progress" in update:
                        friendly_message += " (%s)" % update["progress"]

                if friendly_message is not None:
                    yield friendly_message

    def _build_image(self, driver, taskInfo, buildTask):
        """Build an image for the given buildTask."""

        # Wait for the docker daemon to be ready
        self.docker_daemon.acquire()
        while not self.docker:
            self.docker_daemon.wait()
        self.docker_daemon.release()

        # Now that docker is up, let's go and do stuff
        self._update(driver, taskInfo, self.TASK_RUNNING)

        try:
            sandbox_dir = os.getcwd()
            context_path = os.path.join(sandbox_dir, buildTask.context)

            registry_url = ""
            if buildTask.image.HasField("registry"):
                registry_url = buildTask.image.registry.hostname
                if buildTask.image.registry.HasField("port"):
                    registry_url += ":%d" % buildTask.image.registry.port
                registry_url += "/"

            image_name = "%s%s/%s" % (
                registry_url,
                buildTask.image.repository.username,
                buildTask.image.repository.repo_name
            )

            logger.info("Building image %s from context %s", image_name, context_path)

            if not os.path.exists(context_path):
                raise Exception("Context %s does not exist" % (context_path))

            with open(context_path, "r") as context:
                build_request = self.docker.build(
                    fileobj=context,
                    custom_context=True,
                    encoding="gzip",
                    stream=True
                )

                for message in self._wrap_docker_stream(build_request):
                    driver.sendFrameworkMessage(
                        "%s: %s" % (image_name, message)
                    )

            # Extract the newly created image ID
            match = re.search(r'built (.*)$', message)
            if not match:
                raise Exception("Failed to match image ID from %r" % message)
            image_id = match.group(1)

            # Tag the image with all the required tags
            tags = buildTask.image.tag or ["latest"]
            driver.sendFrameworkMessage("%s: Tagging image %s" % (image_name, image_id))
            for tag in tags:
                try:
                    self.docker.tag(
                        image=image_id,
                        repository=image_name,
                        tag=tag,
                        force=True
                    )
                    driver.sendFrameworkMessage("%s:  ---> %s" % (image_name, tag))
                except Exception, e:
                    raise e

            # Push the image to the registry
            driver.sendFrameworkMessage("%s: Pushing image" % image_name)
            push_request = self.docker.push(image_name, stream=True)
            for message in self._wrap_docker_stream(push_request):
                driver.sendFrameworkMessage(
                    "%s: %s" % (image_name, message)
                )

            self._update(driver, taskInfo, self.TASK_FINISHED)
        except Exception, e:
            logger.error("Caught exception building image: %s", e)
            self._update(driver, taskInfo, self.TASK_FAILED)
