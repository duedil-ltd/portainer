"""The app that runs as the executor, invoked by mesos (thanks to the task info
sent from the portainer scheduler) as "pid one" of the task. Responsible for
invoking the docker daemon, then running `docker build` for the task's staged
context file, and communicating with mesos throughout"""

import docker
import functools
import io
import json
import logging
import mesos.interface
import os
import pesos.executor
import re
import signal
import subprocess
import threading
import time
import traceback
import tempfile
import tarfile

from pesos.vendor.mesos import mesos_pb2

from portainer.app import subcommand
from portainer.proto import portainer_pb2


logger = logging.getLogger("portainer.executor")


@subcommand("build-executor")
def main(args):

    driver = pesos.executor.PesosExecutorDriver(Executor())

    thread = threading.Thread(target=driver.run)
    thread.setDaemon(True)
    thread.start()

    while thread.isAlive():
        time.sleep(0.5)


class Executor(mesos.interface.Executor):

    TASK_STARTING = mesos_pb2.TASK_STARTING
    TASK_RUNNING = mesos_pb2.TASK_RUNNING
    TASK_FINISHED = mesos_pb2.TASK_FINISHED
    TASK_FAILED = mesos_pb2.TASK_FAILED

    def __init__(self):
        self.build_task = None

        self.docker = None
        self.docker_daemon_up = False

    def registered(self, driver, executorInfo, frameworkInfo, slaveInfo):

        logger.info("Setting up environment for building containers")

        # Parse the build task object
        try:
            build_task = portainer_pb2.BuildTask()
            build_task.ParseFromString(executorInfo.data)
        except Exception:
            logger.error("Failed to parse BuildTask in ExecutorInfo.data")
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

            self.docker = docker.Client()
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
            self.docker = docker.Client(build_task.daemon.docker_host)
            self.docker_daemon_up = True

    def disconnected(self, driver):
        logger.info("Disconnected from master! Ahh!")

    def reregistered(self, driver, slaveInfo):
        logger.info("Re-registered from the master! Ahh!")

    def launchTask(self, driver, taskInfo):

        logger.info("Launched task %s", taskInfo.task_id.value)

        # Spawn another thread to run the task, freeing up the executor
        thread = threading.Thread(target=functools.partial(
            self._build_image,
            driver,
            taskInfo,
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

    def _build_image(self, driver, taskInfo, buildTask):
        """Build an image for the given buildTask."""

        # Tell mesos that we're starting the task
        driver.sendStatusUpdate(mesos_pb2.TaskStatus(
            task_id=taskInfo.task_id,
            state=self.TASK_STARTING
        ))

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
            driver.sendStatusUpdate(mesos_pb2.TaskStatus(
                task_id=taskInfo.task_id,
                state=self.TASK_RUNNING
            ))

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

            # Used to store the ID of the image the build is based on, if any
            base_image_id = None

            sandbox_dir = os.environ.get("MESOS_SANDBOX", os.environ["MESOS_DIRECTORY"])
            if buildTask.dockerfile:
                build_request = self.docker.build(
                    fileobj=io.StringIO(buildTask.dockerfile),
                    stream=True
                )

                for message, is_stream in self._wrap_docker_stream(build_request):
                    if message.startswith(u" ---\u003e") and not base_image_id:
                        base_image_id = message[6:]
                    if not is_stream or (is_stream and buildTask.stream):
                        driver.sendFrameworkMessage(
                            ("%s: %s" % (image_name, message)).encode('unicode-escape')
                        )
            else:
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
                        if message.startswith(u" ---\u003e") and not base_image_id:
                            base_image_id = message[6:]
                        if not is_stream or (is_stream and buildTask.stream):
                            driver.sendFrameworkMessage(
                                ("%s: %s" % (image_name, message)).encode('unicode-escape')
                            )

            # Extract the newly created image ID
            match = re.search(r'built (.*)$', message)
            if not match:
                raise Exception("Failed to match image ID from %r" % message)
            image_id = match.group(1)

            # If we've been asked to squash all of the layers for this build into
            # one, do it.
            if buildTask.HasField("squash") and buildTask.squash:
                if not base_image_id:
                    raise Exception("Failed to extract the base image ID to squash against")

                image_id = self._squash_image(
                    driver,
                    sandbox_dir,
                    image_name,
                    base_image_id,
                    image_id
                )

            # Tag the image with all the required tags
            tags = buildTask.image.tag or ["latest"]
            driver.sendFrameworkMessage(str("%s: Tagging image %s" % (image_name, image_id)))
            for tag in tags:
                try:
                    self.docker.tag(
                        image=image_id,
                        repository=image_name,
                        tag=tag,
                        force=True
                    )
                    driver.sendFrameworkMessage(str("%s:    -> %s" % (image_name, tag)))
                except Exception, e:
                    raise e

            # Push the image to the registry
            driver.sendFrameworkMessage(str("%s: Pushing image" % image_name))
            push_request = self.docker.push(image_name, stream=True)
            for message, is_stream in self._wrap_docker_stream(push_request):
                if not is_stream or (is_stream and buildTask.stream):
                    driver.sendFrameworkMessage(
                        str("%s: %s" % (image_name, message))
                    )

            driver.sendStatusUpdate(mesos_pb2.TaskStatus(
                task_id=taskInfo.task_id,
                state=self.TASK_FINISHED
            ))
        except Exception, e:
            logger.error("Caught exception building image: %s", e)
            driver.sendStatusUpdate(mesos_pb2.TaskStatus(
                task_id=taskInfo.task_id,
                state=self.TASK_FAILED,
                message=str(e),
                data=traceback.format_exc()
            ))

            # Re-raise the exception for logging purposes and to terminate the thread
            raise

    def _squash_image(self, driver, sandbox_dir, image_name,
                      base_image_id, head_image_id):
        """
        This method will take the given ImageID and squash all of the layers that
        make it up into a single one. The new ImageID will be returned.
        """

        logger.info("Squashing image from %s to %s", base_image_id[:12], head_image_id[:12])
        driver.sendFrameworkMessage(str("%s: Squashing image" % image_name))

        head_image_id = self.docker.inspect_image(head_image_id)["Id"]

        new_layers = []  # List of layers from HEAD -> BASE (not including BASE)
        total_mb = 0
        for layer in json.loads(self.docker.history(head_image_id)):
            if layer["Id"].startswith(base_image_id):
                base_image_id = layer["Id"]
                break
            new_layers.append(layer["Id"])
            total_mb += layer["Size"] / 1024.0 / 1024.0

        driver.sendFrameworkMessage(str("%s:  ---> Squashing %d layers (%.2fMB)" % (image_name, len(new_layers), total_mb)))

        # Download a tarball of the image layers
        driver.sendFrameworkMessage(str("%s:  ---> Exporting image from docker daemon" % image_name))
        _, layers_tar_name = tempfile.mkstemp(dir=sandbox_dir, suffix=".tar")
        layers_tar_fh = open(layers_tar_name, "wb+")
        for chunk in self.docker.get_image(head_image_id).stream():
            layers_tar_fh.write(chunk)

        layers_tar_fh.seek(0)
        layers_tar = tarfile.open(fileobj=layers_tar_fh)

        # Loop over each layer applying the contents to the final image
        # directory (root_fs_dir)
        root_fs_dir = tempfile.mkdtemp(dir=sandbox_dir)
        seen_paths = set()
        for layer_id in new_layers:
            short_layer_id = layer_id[:12]

            driver.sendFrameworkMessage(str("%s:  ---> Extracting layer %s" % (image_name, short_layer_id)))
            layer_tar_path = tempfile.mkdtemp(dir=sandbox_dir)
            layer_member = os.path.join(layer_id, "layer.tar")
            layers_tar.extract(
                member=layer_member,
                path=layer_tar_path
            )

            layer = tarfile.open(os.path.join(layer_tar_path, layer_member))

            driver.sendFrameworkMessage(str("%s:      -> Applying layer %s" % (image_name, short_layer_id)))
            for member in layer.getnames():
                parent, leaf = os.path.split(member)
                if member.startswith(".wh..wh"):
                    logger.info("Skipped whiteout file %s", member)
                    continue
                if leaf.startswith(".wh."):
                    seen_paths.add(os.path.join(parent, leaf[4:]))
                    try:
                        os.makedirs(os.path.dirname(os.path.join(root_fs_dir, member)))
                    except:
                        pass
                    with open(os.path.join(root_fs_dir, member), "wb") as fh:
                        fh.write("")
                elif member not in seen_paths:
                    layer.extract(member=member, path=root_fs_dir)
                    seen_paths.add(member)

        # Generate the new layer tarball
        driver.sendFrameworkMessage(str("%s:  ---> Creating tar for squashed layer" % image_name))
        _, new_layer_tarball_path = tempfile.mkstemp(dir=sandbox_dir, suffix=".tar")
        new_layer_tarball = tarfile.open(new_layer_tarball_path, "w")
        for path in os.listdir(root_fs_dir):
            new_layer_tarball.add(os.path.join(root_fs_dir, path), arcname=path)
        new_layer_tarball.close()

        # Generate the new image tarball
        driver.sendFrameworkMessage(str("%s:  ---> Creating image tarball for image %s with parent %s" % (image_name, head_image_id[:12], base_image_id[:12])))
        _, new_image_tarball_path = tempfile.mkstemp(dir=sandbox_dir, suffix=".tar.gz")
        new_image_tarball = tarfile.open(new_image_tarball_path, "w:gz")
        new_image_tarball.add(new_layer_tarball_path, arcname=os.path.join(head_image_id, "layer.tar"))

        layers_tar.extract(os.path.join(head_image_id, "VERSION"), path=sandbox_dir)
        layers_tar.extract(os.path.join(head_image_id, "json"), path=sandbox_dir)

        image_info = None
        with open(os.path.join(sandbox_dir, head_image_id, "json"), "r") as json_info:
            image_info = json.load(json_info)

        image_info["parent"] = base_image_id
        image_info["config"]["Image"] = base_image_id
        image_info["container_config"]["Image"] = base_image_id
        with open(os.path.join(sandbox_dir, head_image_id, "json"), "w") as json_info:
            json.dump(image_info, json_info)

        new_image_tarball.add(os.path.join(sandbox_dir, head_image_id, "VERSION"), arcname=os.path.join(head_image_id, "VERSION"))
        new_image_tarball.add(os.path.join(sandbox_dir, head_image_id, "json"), arcname=os.path.join(head_image_id, "json"))

        new_image_tarball.close()

        driver.sendFrameworkMessage(str("%s:  ---> Uploading squashed image to docker" % image_name))

        with open(new_image_tarball_path, "r") as fh:
            self.docker.remove_image(head_image_id, force=True)
            self.docker.load_image(fh)

        return head_image_id
