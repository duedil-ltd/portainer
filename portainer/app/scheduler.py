"""
"""

import logging
import os
import mesos.interface
import progressbar
import sys
import StringIO
import tarfile
import tempfile
import threading
import traceback
import uuid

from fnmatch import fnmatch
from functools import partial
from fs.opener import opener
from pesos.vendor.mesos import mesos_pb2
from urlparse import urlparse

from portainer.proto import portainer_pb2
from portainer.util.parser import parse_dockerfile, parse_dockerignore

logger = logging.getLogger("portainer.scheduler")


class TaskContextException(Exception):
    pass


class StagingSystemRequiredException(Exception):
    pass


class Scheduler(mesos.interface.Scheduler):
    """Mesos scheduler that is responsible for launching the builder tasks."""

    def __init__(self, tasks, executor_uri, cpu_limit, mem_limit, push_registry,
                 staging_uri, stream=False, verbose=False, repository=None,
                 pull_registry=None, docker_host=None):

        self.executor_uri = executor_uri
        self.cpu = float(cpu_limit)
        self.mem = int(mem_limit)
        self.push_registry = push_registry
        self.pull_registry = pull_registry
        self.staging_uri = staging_uri
        self.stream = stream
        self.verbose = verbose
        self.repository = repository
        self.docker_host = docker_host

        self.queued_tasks = []
        for path, tags in tasks:
            dockerfile = parse_dockerfile(path, registry=pull_registry)
            self.queued_tasks.append((path, dockerfile, tags))

        self.pending = len(self.queued_tasks)
        self.running = 0
        self.finished = 0
        self.failed = 0
        self.task_ids = {}

        self.processing_offers = threading.Lock()

        # Ensure the staging directory exists
        self.filesystem = None
        if self.staging_uri:
            staging_uri = urlparse(self.staging_uri)
            staging_fs = opener.opendir(
                "%s://%s/" % (staging_uri.scheme, staging_uri.netloc)
            )

            staging_fs.makedir(
                staging_uri.path.lstrip("/"),
                recursive=True,
                allow_recreate=True
            )

            self.filesystem = opener.opendir(self.staging_uri)

    def registered(self, driver, frameworkId, masterInfo):
        host = masterInfo.hostname or masterInfo.ip
        master = "http://%s:%s" % (host, masterInfo.port)
        logger.info("Framework %s registered to %s", frameworkId.value, master)

    def disconnected(self, driver):
        logger.warning("Framework disconnected from the mesos master")

    def reregistered(self, driver, masterInfo):
        host = masterInfo.hostname or masterInfo.ip
        master = "http://%s:%s" % (host, masterInfo.port)
        logger.info("Framework re-registered to %s", master)

    def error(self, driver, message):
        logger.error("Framework error: %s", message)

    def resource_offers(self, driver, offers):

        # Spawn another thread to handle offer processing to free up the driver
        t = threading.Thread(target=partial(
            self._handle_offers,
            driver,
            offers
        ))

        t.setDaemon(True)
        t.start()

    def _handle_offers(self, driver, offers):

        # We only want to process offers one set at a time
        with self.processing_offers:
            tasks_to_launch = []

            if not self.pending:
                for offer in offers:
                    driver.declineOffer(offer.id)
            else:
                for offer in offers:
                    offer_cpu = 0.0
                    offer_mem = 0

                    # Extract the important resources from the offer
                    for resource in offer.resources:
                        if resource.name == "cpus":
                            offer_cpu = float(resource.scalar.value)
                        if resource.name == "mem":
                            offer_mem = int(resource.scalar.value)

                    logger.debug("Received offer for cpus:%f mem:%d", offer_cpu, offer_mem)

                    # Look for a task in the queue that fits the bill
                    for idx, (path, dockerfile, tags) in enumerate(self.queued_tasks):
                        cpu = float(dockerfile.get("BUILD_CPU", [self.cpu]).next()[0])
                        mem = int(dockerfile.get("BUILD_MEM", [self.mem]).next()[0])

                        if cpu <= offer_cpu and mem <= offer_mem:
                            self.queued_tasks[idx] = None  # Remove the task from the queue
                            self.pending -= 1
                            self.running += 1
                            tasks_to_launch.append((offer, path, dockerfile,
                                                    tags, cpu, mem))
                            # TODO: No support for multiple tasks per offer yet
                            break
                    else:
                        logger.debug("Ignoring offer %r", offer)
                        driver.declineOffer(offer.id)

                    # Remove all of the tasks that are about to be launched
                    self.queued_tasks = filter(None, self.queued_tasks)

            # Launch the build tasks on the mesos cluster
            for offer, path, dockerfile, tags, cpu, mem in tasks_to_launch:
                # Generate a task ID
                task_id = str(uuid.uuid1())

                try:
                    tasks = [self._prepare_task(
                        driver=driver,
                        task_id=task_id,
                        path=path,
                        dockerfile=dockerfile,
                        tags=tags,
                        offer=offer,
                        cpu=cpu,
                        mem=mem
                    )]
                except TaskContextException as e:
                    logger.error("Caught exception: %s", e.message)
                    self.failed += 1
                    self.running -= 1
                    tasks = []
                except StagingSystemRequiredException as e:
                    logger.error("Caught exception: %s", e.message)
                    self.failed += 1
                    self.running -= 1
                    tasks = []

                if not tasks:
                    logger.error("Task %s failed to launch", task_id)

                    # If there's no pending tasks or any tasks running, stop
                    # the driver.
                    if (self.pending + self.running) == 0:
                        driver.stop()
                else:
                    logger.info("Launching %d tasks", len(tasks))
                    driver.launchTasks(offer.id, tasks)

    def status_update(self, driver, update):
        """Called when a status update is received from the mesos cluster."""

        finished = False
        failed = False
        task_id = None

        if update.task_id.value in self.task_ids:
            build_task = self.task_ids[update.task_id.value]
            task_id = build_task.image.repository
        else:
            task_id = update.task_id.value
            logger.error("Task update for unknown task! %s", task_id)

        if update.state == mesos_pb2.TASK_STARTING:
            logger.info("Task update %s : STARTING", task_id)
        if update.state == mesos_pb2.TASK_RUNNING:
            logger.info("Task update %s : RUNNING", task_id)
        if update.state == mesos_pb2.TASK_FAILED:
            logger.info("Task update %s : FAILED", task_id)
            if update.message and update.data:
                logger.info("Exception caught while building image: \n\n%s", update.data)
            failed = True
        elif update.state == mesos_pb2.TASK_FINISHED:
            logger.info("Task update %s : FINISHED", task_id)
            finished = True
        elif update.state == mesos_pb2.TASK_KILLED:
            logger.info("Task update %s : KILLED", task_id)
            failed = True
        elif update.state == mesos_pb2.TASK_LOST:
            logger.info("Task update %s : LOST", task_id)
            failed = True

        if finished:
            self.running -= 1
            self.finished += 1
        elif failed:
            self.running -= 1
            self.failed += 1

        # If there are no tasks running, and the queue is empty, we should stop
        if self.running == 0 and self.pending == 0:
            driver.stop()

    def framework_message(self, driver, executorId, slaveId, message):
        if "Buffering" in message:  # Heh. This'll do for now, eh?
            logger.debug("\t%s", message)
        else:
            logger.info("\t%s", message)

    def _prepare_task(self, driver, task_id, path, dockerfile, tags, offer, cpu, mem):
        """Prepare a given dockerfile build task atop the given mesos offer."""

        logger.info("Preparing task %s to build %s", task_id, path)

        # Define the build that's required
        build_task = portainer_pb2.BuildTask()
        build_task.stream = self.stream

        # Create a custom docker context if there are local sources
        staging_context_path = None
        if dockerfile.has_local_sources:
            working_dir = os.path.abspath(os.path.dirname(path))

            # Generate the dockerfile build context
            _, context_path = tempfile.mkstemp()
            context = open(context_path, "w+b")

            logger.debug("Writing context tar to %s", context_path)
            context_size = self._make_build_context(context, working_dir, dockerfile)

            # Put together the staging directory
            staging_dir = os.path.join("staging", task_id)
            context_filename = "docker_context.tar.gz"

            staging_context_path = os.path.join(staging_dir, context_filename)

            # Create the directory
            logger.debug("Task staging directory %s", staging_dir)
            self.filesystem.makedir(staging_dir, recursive=True)

            # Upload the build context (+ fancy progress bar)
            logger.info("Uploading context (%d bytes)", context_size)
            pbar = progressbar.ProgressBar(maxval=context_size, term_width=100)

            # Define a custom error handler for the async upload
            caught_exception = threading.Event()

            def handle_exception(e):
                (_, _, tb) = sys.exc_info()
                logger.error("Caught exception uploading the context: %s" % e.message)
                logger.error(traceback.format_exc(tb))
                caught_exception.set()

            event = self.filesystem.setcontents_async(
                path=staging_context_path,
                data=context,
                progress_callback=pbar.update,
                finished_callback=pbar.finish,
                error_callback=handle_exception
            )

            # Hold up, let's wait until the upload finishes
            event.wait()

            # Close and clear up the tmp context
            logger.debug("Cleaning up local context %s", context_path)
            context.close()
            os.unlink(context_path)

            # Check to see if we caught any exceptions while uploading the context
            if caught_exception.is_set():
                raise TaskContextException("Exception raised while uploading context")

            build_task.context = context_filename
        else:
            build_task.dockerfile = dockerfile.build()

        if self.docker_host:
            build_task.docker_host = self.docker_host

        # Pull out the repository from the dockerfile
        try:
            build_task.image.repository = dockerfile.get("REPOSITORY", [self.repository]).next()[0]
        except (StopIteration, IndexError):
            raise ValueError("No REPOSITORY given for %s", path)

        # Pull out the registry from the dockerfile
        try:
            registry = self.push_registry.split(":")
            build_task.image.registry.hostname = registry[0]
            if len(registry) > 1:
                build_task.image.registry.port = int(registry[1])
        except ValueError:
            raise ValueError("Failed to parse REGISTRY in %s", path)

        # Add any tags
        build_task.image.tag.extend(tags)

        # Define the mesos task
        task = mesos_pb2.TaskInfo()
        task.name = "%s/%s" % (":".join(registry), build_task.image.repository)
        task.task_id.value = task_id
        task.slave_id.value = offer.slave_id.value

        # Create the executor
        args = []
        if self.verbose:
            args.append("--verbose")

        task.executor.executor_id.value = task_id
        task.executor.command.value = "./%s/bin/portainer %s build-executor" % (
            os.path.basename(self.executor_uri).rstrip(".tar.gz"), " ".join(args)
        )

        # TODO(tarnfeld): Make this configurable
        # TODO(tarnfeld): Support the mesos 0.20.0 docker protobuf
        task.executor.command.container.image = "docker://jpetazzo/dind"

        # We have to mount the /var/lib/docker VOLUME inside of the sandbox
        task.executor.command.container.options.extend(["--privileged"])
        task.executor.command.container.options.extend(["-v", "$MESOS_DIRECTORY/docker:/var/lib/docker"])

        task.executor.name = "build"
        task.executor.source = "portainer"

        # Configure the mesos executor with the portainer executor uri
        portainer_executor = task.executor.command.uris.add()
        portainer_executor.value = self.executor_uri

        if staging_context_path:
            # Add the docker context
            uri = task.executor.command.uris.add()
            uri.value = os.path.join(self.staging_uri, staging_context_path)
            uri.extract = False

        task.data = build_task.SerializeToString()
        task.executor.data = task.data

        # Build up the resources
        cpu_resource = task.resources.add()
        cpu_resource.name = "cpus"
        cpu_resource.type = mesos_pb2.Value.SCALAR
        cpu_resource.scalar.value = cpu

        mem_resource = task.resources.add()
        mem_resource.name = "mem"
        mem_resource.type = mesos_pb2.Value.SCALAR
        mem_resource.scalar.value = mem

        self.task_ids[task_id] = build_task

        logger.info("Prepared task %s to build %s", task_id, path)
        logger.debug("%s", build_task)

        return task

    def _make_build_context(self, output, context_root, dockerfile):
        """Generate and return a compressed tar archive of the build context."""

        if not self.filesystem:
            raise StagingSystemRequiredException("A staging filesystem is required for local sources")

        tar = tarfile.open(mode="w:gz", fileobj=output)
        for idx, (cmd, instruction) in enumerate(dockerfile.instructions):
            if cmd == "ADD":
                local_path, remote_path = instruction
                tar_path = "context/%s" % str(idx)

                # TODO(tarnfeld): This isn't strict enough
                if local_path.startswith("http"):
                    logger.debug("Skipping remote ADD %s", local_path)
                    continue

                if not local_path.startswith("/"):
                    local_path = os.path.join(context_root, local_path)
                local_path = os.path.abspath(local_path)

                if os.path.isfile(local_path):
                    # Preserve the file extension
                    parts = local_path.split(".")
                    if len(parts) > 1:
                        tar_path += "." + parts[-1]
                    logger.debug("Adding path %s to tar in %s", local_path, tar_path)
                    tar.add(local_path, arcname=tar_path)
                else:
                    ignore = set()
                    for (dirpath, _, filenames) in os.walk(local_path, followlinks=True):
                        # Update the set of ignored paths with any new .dockerignore files we see
                        ignore_path = os.path.join(dirpath, ".dockerignore")
                        if os.path.exists(ignore_path):
                            with open(ignore_path, 'r') as f:
                                for glob in parse_dockerignore(f):
                                    ignore.add(os.path.join(dirpath, glob) + "*")

                        for filename in filenames:
                            path = os.path.join(dirpath, filename)
                            for expr in ignore:
                                if fnmatch(path, expr):
                                    logger.debug("Ignoring path %s", path)
                                    break
                            else:
                                rel_path = path.replace(local_path, '').lstrip('/')
                                logger.debug("Adding path %s to tar in %s", rel_path, tar_path)
                                tar.add(path, arcname=os.path.join(tar_path, rel_path))

                dockerfile.instructions[idx] = (cmd, (tar_path, remote_path))

        # Write the modified dockerfile into the tar also
        buildfile = StringIO.StringIO()
        buildfile.write("# Generated by portainer\n")

        for cmd, instructions in dockerfile.instructions:
            if cmd not in dockerfile.INTERNAL:
                line = "%s %s" % (cmd, " ".join(instructions))

                logger.debug("Adding instruction %r to dockerfile", line)
                buildfile.write("%s\n" % line)

        buildfile.seek(0, os.SEEK_END)
        info = tarfile.TarInfo("Dockerfile")
        info.size = buildfile.tell()

        buildfile.seek(0)
        tar.addfile(info, fileobj=buildfile)

        tar.close()
        output.seek(0, os.SEEK_END)
        tar_size = output.tell()
        output.seek(0)

        return tar_size
