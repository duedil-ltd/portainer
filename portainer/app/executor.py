"""The app that runs as the executor, invoked by mesos (thanks to the task info
sent from the portainer scheduler) as "pid one" of the task. Responsible for
invoking the docker daemon, then running `docker build` for the task's staged
context file, and communicating with mesos throughout"""

import base64
import docker
import functools
import io
import json
import logging
import os
import pymesos
import re
import signal
import subprocess
import threading
import time
import traceback

from portainer.app import subcommand
from portainer.proto import portainer_pb2

logger = logging.getLogger("portainer.executor")


@subcommand("build-executor")
def main(args):
    driver = pymesos.MesosExecutorDriver(Executor())

    thread = threading.Thread(target=driver.run)
    thread.setDaemon(True)
    thread.start()

    while thread.isAlive():
        time.sleep(0.5)


class Executor(pymesos.Executor):

    def __init__(self):
        self.build_task = None

        self.docker = None
        self.docker_daemon_up = False

    def registered(self, driver, executorInfo, frameworkInfo, slaveInfo):
        logger.info("Setting up environment for building containers")

        # Parse the build task object
        try:
            build_task = portainer_pb2.BuildTask()
            build_task.ParseFromString(base64.b64decode(executorInfo['data']))
        except Exception:
            logger.error("Failed to parse BuildTask in ExecutorInfo['data']")
            raise

        self.build_task = build_task

        # Launch the docker daemon
        def launch_docker_daemon():
            logger.info("Launching docker daemon subprocess")

            env = dict(os.environ)
            env["DOCKER_DAEMON_ARGS"] = " -g %s" % (
                os.path.join(os.environ.get("MESOS_SANDBOX", os.environ["MESOS_DIRECTORY"]), "docker")
            )

            for reg in build_task.daemon.insecure_registries:
                env["DOCKER_DAEMON_ARGS"] += " --insecure-registry %s" % reg

            # Use the `wrapdocker` script included in our docker image
            proc = subprocess.Popen(["/usr/local/bin/wrapdocker"], env=env)

            self.docker = docker.APIClient()
            while True:
                try:
                    self.docker.ping()
                except:
                    logger.info("Waiting for docker daemon to respond to pings")
                    time.sleep(1)
                else:
                    self.docker_daemon_up = True
                    break

            proc.wait()

        if not build_task.daemon.HasField("docker_host"):
            daemon_thread = threading.Thread(target=launch_docker_daemon)
            daemon_thread.setDaemon(True)
            daemon_thread.start()
        else:
            self.docker = docker.APIClient(base_url=build_task.daemon.docker_host)
            self.docker_daemon_up = True

    def reregistered(self, driver, slaveInfo):
        logger.info("Re-registered to master! Ahh!")

    def disconnected(self, driver):
        logger.info("Disconnected from master! Ahh!")

    def launchTask(self, driver, task):
        logger.info("Launched task %s", task['task_id']['value'])

        # Spawn another thread to run the task, freeing up the executor
        thread = threading.Thread(target=functools.partial(
            self._build_image,
            driver,
            task,
            self.build_task
        ))

        thread.setDaemon(True)
        thread.start()

    def shutdown(self, driver):
        logger.info("Shutting down the executor")
        if os.path.exists("/var/run/docker.pid"):
            try:
                docker_pid = int(open("/var/run/docker.pid", "r").read())
                os.kill(docker_pid, signal.SIGTERM)
            except Exception, e:
                logger.error("Caught exception killing docker daemon")
                logger.error(e)
        else:
            logger.warning("Unable to locate docker pidfile")

    def _build_image(self, driver, taskInfo, buildTask):
        """Build an image for the given buildTask."""

        # Tell mesos that we're starting the task
        driver.sendStatusUpdate({
            'task_id': taskInfo['task_id'],
            'state': 'TASK_STARTING'
        })

        logger.info("Waiting for docker daemon to be available")

        # Wait for the docker daemon to be ready (up to 30 seconds)
        timeout = 30
        while timeout > 1 and not self.docker_daemon_up:
            timeout -= 1
            time.sleep(1)

        try:
            if not self.docker_daemon_up:
                raise Exception("Timed out waiting for docker daemon")

            # Now that docker is up, let's go and do stuff
            driver.sendStatusUpdate({
                'task_id': taskInfo['task_id'],
                'state': 'TASK_RUNNING'
            })

            if not buildTask:
                raise Exception("Failed to decode the BuildTask protobuf data")

            if not buildTask.context and not buildTask.dockerfile:
                raise Exception("Either a build context or dockerfile is required")

            registry_url = None
            if buildTask.image.HasField("registry"):
                registry_url = buildTask.image.registry.hostname
                if buildTask.image.registry.HasField("port"):
                    registry_url += ":%d" % buildTask.image.registry.port
                registry_url += "/"

            if not registry_url:
                raise Exception("No registry URL provided")

            image_name = registry_url + buildTask.image.repository
            logger.info("Building image %s", image_name)

            if buildTask.dockerfile:
                build_request = self.docker.build(
                    fileobj=io.StringIO(buildTask.dockerfile),
                    stream=True
                )

                for message, is_stream in self._wrap_docker_stream(build_request):
                    if not is_stream or (is_stream and buildTask.stream):
                        driver.sendFrameworkMessage(
                            base64.b64encode("%s: %s" % (image_name, message))
                        )
            else:
                sandbox_dir = os.environ.get("MESOS_SANDBOX", os.environ["MESOS_DIRECTORY"])
                context_path = os.path.join(sandbox_dir, buildTask.context)

                if not os.path.exists(context_path):
                    raise Exception("Context %s does not exist" % (context_path))

                with open(context_path, "r") as context:
                    build_request = self.docker.build(
                        fileobj=context,
                        custom_context=True,
                        encoding="gzip",
                        stream=True
                    )

                    for message, is_stream in self._wrap_docker_stream(build_request):
                        if not is_stream or (is_stream and buildTask.stream):
                            driver.sendFrameworkMessage(
                                base64.b64encode("%s: %s" % (image_name, message))
                            )

            # Extract the newly created image ID
            match = re.search(r'built (.*)$', message)
            if not match:
                raise Exception("Failed to match image ID from %r" % message)
            image_id = match.group(1)

            # Tag the image with all the required tags
            tags = buildTask.image.tag or ["latest"]
            driver.sendFrameworkMessage(base64.b64encode("%s: Tagging image %s" % (image_name, image_id)))
            for tag in tags:
                try:
                    self.docker.tag(
                        image=image_id,
                        repository=image_name,
                        tag=tag,
                        force=True
                    )
                    driver.sendFrameworkMessage(base64.b64encode("%s:    -> %s" % (image_name, tag)))
                except Exception, e:
                    raise e

            # Push the image to the registry
            driver.sendFrameworkMessage(base64.b64encode("%s: Pushing image" % image_name))
            push_request = self.docker.push(image_name, stream=True)
            for message, is_stream in self._wrap_docker_stream(push_request):
                if not is_stream or (is_stream and buildTask.stream):
                    driver.sendFrameworkMessage(
                        base64.b64encode("%s: %s" % (image_name, message))
                    )

            driver.sendStatusUpdate({
                'task_id': taskInfo['task_id'],
                'state': 'TASK_FINISHED'
            })
        except Exception, e:
            logger.error("Caught exception building image: %s", e)
            driver.sendStatusUpdate({
                'task_id': taskInfo['task_id'],
                'state': 'TASK_FAILED',
                'message': str(e),
                'data': base64.b64encode(traceback.format_exc())
            })

            # Re-raise the exception for logging purposes and to terminate the thread
            raise

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
                    yield update["error"], False
                    raise Exception("Docker encountered an error")

                friendly_message = None
                is_stream = False

                if "stream" in update:
                    is_stream = True
                    friendly_message = re.sub(r'\033\[[0-9;]*m', '',
                                              update["stream"].rstrip())
                if "status" in update:
                    friendly_message = update["status"].rstrip()
                    if "id" in update:
                        friendly_message = "[%s] %s" % (update["id"], friendly_message)
                    if "progress" in update:
                        friendly_message += " (%s)" % update["progress"]

                if friendly_message is not None:
                    yield friendly_message, is_stream
