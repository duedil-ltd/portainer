"""
"""

import logging
import os
import mesos.interface
import progressbar
import StringIO
import tarfile
import tempfile
import threading
import uuid

from fs.opener import opener
from pesos.vendor.mesos import mesos_pb2
from urlparse import urlparse

from portainer.proto import portainer_pb2
from portainer.util.parser import parse_dockerfile

logger = logging.getLogger("portainer.scheduler")


class Scheduler(mesos.interface.Scheduler):
    """Mesos scheduler that is responsible for launching the builder tasks."""

    def __init__(self, tasks, executor_uri, cpu_limit, mem_limit,
                 registry, repository, variables, args):
        self.executor_uri = executor_uri
        self.cpu = float(cpu_limit)
        self.mem = int(mem_limit)
        self.registry = registry
        self.repository = repository
        self.args = args

        if registry:
            variables["registry"] = registry

        # Parse and sort the task queue with the smallest CPU requirement first
        self.queued_tasks = sorted(
            [(d, parse_dockerfile(d, variables), t) for d, t in tasks],
            key=lambda (p, d, t): float(d.get("BUILD_CPU", [self.cpu]).next()[0])
        )

        self.pending = len(self.queued_tasks)
        self.running = 0
        self.finished = 0
        self.task_ids = {}

        self.processing_offers = threading.Lock()

        # Ensure the staging directory exists
        staging_uri = urlparse(self.args.staging_uri)
        staging_fs = opener.opendir(
            "%s://%s/" % (staging_uri.scheme, staging_uri.netloc)
        )

        staging_fs.makedir(
            staging_uri.path.lstrip("/"),
            recursive=True,
            allow_recreate=True
        )

        self.filesystem = opener.opendir(self.args.staging_uri)

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
        """Called when resource offers are sent from the mesos cluster."""

        # Spawn another thread to handle offer processing to free up the driver
        def handle_offers():
            with self.processing_offers:
                decline_offers = []
                for offer in offers:
                    offer_cpu = 0.0
                    offer_mem = 0

                    if not self.pending:
                        decline_offers.append(offer.id)
                        continue

                    for resource in offer.resources:
                        if resource.name == "cpus":
                            offer_cpu = float(resource.scalar.value)
                        if resource.name == "mem":
                            offer_mem = int(resource.scalar.value)

                    # Look for a task in the queue that fits the bill
                    to_launch = []
                    for idx, (path, dockerfile, tags) in enumerate(self.queued_tasks):
                        cpu = float(dockerfile.get("BUILD_CPU", [self.cpu]).next()[0])
                        mem = int(dockerfile.get("BUILD_MEM", [self.mem]).next()[0])

                        if cpu > offer_cpu:
                            break
                        if mem <= offer_mem:
                            to_launch.append((idx, cpu, mem))
                            break  # TODO: No support for multiple tasks per offer yet

                    if to_launch:
                        tasks = []
                        task_queue = list(self.queued_tasks)

                        for idx, cpu, mem in to_launch:
                            path, dockerfile, tgs = task_queue[idx]
                            task_queue[idx] = None  # Null out the value to be removed later

                            tasks.append(self._prepare_task(
                                driver=driver,
                                path=path,
                                dockerfile=dockerfile,
                                tags=tags,
                                offer=offer,
                                cpu=cpu,
                                mem=mem
                            ))

                        self.queued_tasks = filter(None, task_queue)
                        self.pending -= len(tasks)
                        self.running += len(tasks)

                        logger.info("Launching %d tasks", len(tasks))
                        driver.launchTasks(offer.id, tasks)
                    else:
                        logger.debug("Ignoring offer %r", offer)
                        decline_offers.append(offer.id)

                if decline_offers:
                    driver.declineOffer(decline_offers)

        t = threading.Thread(target=handle_offers)
        t.setDaemon(True)
        t.start()

    def status_update(self, driver, update):
        """Called when a status update is received from the mesos cluster."""

        done = False
        task_id = None

        if update.task_id.value in self.task_ids:
            build_task = self.task_ids[update.task_id.value]
            task_id = "%s/%s" % (build_task.image.repository.username,
                                 build_task.image.repository.repo_name)
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
                logger.info("Exception caught while building image:")
            done = True
        elif update.state == mesos_pb2.TASK_FINISHED:
            logger.info("Task update %s : FINISHED", task_id)
            done = True
        elif update.state == mesos_pb2.TASK_KILLED:
            logger.info("Task update %s : KILLED", task_id)
            done = True
        elif update.state == mesos_pb2.TASK_LOST:
            logger.info("Task update %s : LOST", task_id)
            done = True

        # If the status update is terminal, go ahead and mark the task as done
        if done:
            self.running -= 1
            self.finished += 1

        # If there are no tasks running, and the queue is empty, it should be
        # save to quit.
        if self.running == 0 and self.pending == 0:
            driver.stop()

    def framework_message(self, driver, executorId, slaveId, message):
        if "Buffering" in message:  # Heh. This'll do for now, eh?
            logger.debug(message)
        else:
            logger.info(message)

    def _prepare_task(self, driver, path, dockerfile, tags, offer, cpu, mem):
        """Prepare a given dockerfile build task atop the given mesos offer."""

        # Generate a task ID
        task_id = str(uuid.uuid1())
        logger.info("Preparing task %s to build %s", task_id, path)

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
        event = self.filesystem.setcontents_async(
            path=staging_context_path,
            data=context,
            progress_callback=pbar.update,
            finished_callback=pbar.finish
        )

        # Hold up, let's wait until the upload finishes
        event.wait()

        # Close and clear up the tmp context
        logger.debug("Cleaning up local context %s", context_path)
        context.close()
        os.unlink(context_path)

        # Define the build that's required
        build_task = portainer_pb2.BuildTask()
        build_task.context = context_filename
        build_task.stream = self.args.stream

        if self.args.docker_host:
            build_task.docker_host = self.args.docker_host
        if self.args.docker_args:
            build_task.docker_args = self.args.docker_args

        # Pull out the repository from the dockerfile
        try:
            user, repo = dockerfile.get("REPOSITORY", [self.repository]).next()[0].split("/")
            build_task.image.repository.username = user
            build_task.image.repository.repo_name = repo
        except ValueError:
            raise ValueError("Failed to parse REPOSITORY in %s", path)
        except (StopIteration, IndexError):
            raise ValueError("No REPOSITORY given for %s", path)

        # Pull out the registry from the dockerfile
        try:
            registry = dockerfile.get("REGISTRY", [self.registry]).next()[0].split(":")
            build_task.image.registry.hostname = registry[0]
            if len(registry) > 1:
                build_task.image.registry.port = int(registry[1])
        except ValueError:
            raise ValueError("Failed to parse REGISTRY in %s", path)
        except (StopIteration, IndexError):
            raise ValueError("No REGISTRY given for %s", path)

        # Add any tags
        build_task.image.tag.extend(tags)

        # Define the mesos task
        task = mesos_pb2.TaskInfo()
        task.name = "Repository: %s/%s Registry: %s" % (user, repo, ":".join(registry))
        task.task_id.value = task_id
        task.slave_id.value = offer.slave_id.value

        # Create the executor
        args = []
        if self.args.verbose:
            args.append("--verbose")

        task.executor.executor_id.value = task_id
        task.executor.command.value = "./%s/bin/portainer %s build-executor" % (
            os.path.basename(self.executor_uri).rstrip(".tar.gz"), " ".join(args)
        )
        task.executor.command.container.image = "docker://jpetazzo/dind"

        # We have to mount the /var/lib/docker VOLUME inside of the sandbox
        task.executor.command.container.options.extend(["--privileged"])
        task.executor.command.container.options.extend(["-v", "$MESOS_DIRECTORY/docker:/var/lib/docker"])

        task.executor.name = "Docker Build Executor"
        task.executor.source = "portainer"

        # Configure the mesos executor with the portainer executor uri
        portainer_executor = task.executor.command.uris.add()
        portainer_executor.value = self.executor_uri

        # Add the docker context
        uri = task.executor.command.uris.add()
        uri.value = os.path.join(self.args.staging_uri, staging_context_path)
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

        return task

    def _make_build_context(self, output, context_root, dockerfile):
        """Generate and return a compressed tar archive of the build context."""

        tar = tarfile.open(mode="w:gz", fileobj=output)
        for idx, (cmd, instruction) in enumerate(dockerfile.instructions):
            if cmd == "ADD":
                local_path, remote_path = instruction
                tar_path = "context/%s" % str(idx)

                if local_path.startswith("http"):
                    continue

                if not local_path.startswith("/"):
                    local_path = os.path.join(context_root, local_path)
                local_path = os.path.abspath(local_path)

                logger.debug("Adding path %s to tar at %s", local_path, tar_path)

                # TODO(tarnfeld): Take note of .dockerignore files
                tar.add(local_path, arcname=tar_path)
                dockerfile.instructions[idx] = (cmd, (tar_path, remote_path))

        # Write the modified dockerfile into the tar also
        buildfile = StringIO.StringIO()
        buildfile.write("# Generated by portainer\n")

        for cmd, instructions in dockerfile.instructions:
            if cmd not in dockerfile.INTERNAL:
                line = "%s %s" % (cmd, " ".join(instructions))

                logger.debug("Added command %r to new dockerfile", line)
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
