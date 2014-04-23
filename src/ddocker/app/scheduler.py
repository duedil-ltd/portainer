"""
"""

import logging
import mesos
import os
import progressbar
import StringIO
import tarfile
import tempfile
import uuid

from fs.osfs import OSFS
from fs.s3fs import S3FS
from urlparse import urlparse

from ddocker.proto import ddocker_pb2
from ddocker.proto import mesos_pb2
from ddocker.util.parser import parse_dockerfile

logger = logging.getLogger("ddocker.scheduler")


class Scheduler(mesos.Scheduler):
    """Mesos scheduler that is responsible for launching the builder tasks."""

    def __init__(self, task_queue, executor, cpu_limit, mem_limit, args):
        self.task_queue = task_queue
        self.executor = executor
        self.cpu = cpu_limit
        self.mem = mem_limit
        self.args = args

        self.running = 0

        self.filesystem = self._create_filesystem(
            staging_uri=self.args.staging_uri,
            s3_key=self.args.aws_access_key_id,
            s3_secret=self.args.aws_secret_access_key
        )

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

    def slaveLost(self, driver, slaveId):
        pass

    def resourceOffers(self, driver, offers):
        """Called when resource offers are sent from the mesos cluster."""

        if self.task_queue.empty():
            return

        logger.debug("Received %d offers", len(offers))

        for offer in offers:
            offer_cpu = 0.0
            offer_mem = 0

            for resource in offer.resources:
                if resource.name == "cpus":
                    offer_cpu = resource.scalar
                if resource.name == "mem":
                    offer_mem = resource.scalar

            # Launch the task if applicable
            if offer_cpu >= self.cpu and offer_mem >= self.mem:
                try:
                    self._launchTask(driver, self.task_queue.get(), offer)
                except Exception, e:
                    logger.error("Caught exception launching task %r", e)
                    self.task_queue.task_done()
            else:
                logger.debug("Ignoring offer %r", offer)

    def statusUpdate(self, driver, update):
        """Called when a status update is received from the mesos cluster."""

        done = False

        if update.state == mesos_pb2.TASK_FAILED:
            logger.info("Task update %s : FAILED", update.task_id.value)
            done = True
        elif update.state == mesos_pb2.TASK_FINISHED:
            logger.info("Task update %s : FINISHED", update.task_id.value)
            done = True
        elif update.state == mesos_pb2.TASK_KILLED:
            logger.info("Task update %s : KILLED", update.task_id.value)
            done = True
        elif update.state == mesos_pb2.TASK_LOST:
            logger.info("Task update %s : LOST", update.task_id.value)
            done = True

        # If the status update is terminal, go ahead and mark the task as done
        if done:
            self.task_queue.task_done()
            self.running -= 1

        # If there are no tasks running, and the queue is empty, it should be
        # save to quit.
        if self.running == 0 and self.task_queue.empty():
            driver.stop()

    def _launchTask(self, driver, path, offer):
        """Launch a given dockerfile build task atop the given mesos offer."""

        # Generate a task ID
        task_id = str(uuid.uuid1())
        logger.info("Prepping task %s to build %s", task_id, path)

        working_dir = os.path.abspath(os.path.dirname(path))

        # Parse the dockerfile
        dockerfile = parse_dockerfile(path)

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
        logger.info("Cleaning up local context %s", context_path)
        context.close()
        os.unlink(context_path)

        # Define the build that's required
        build_task = ddocker_pb2.BuildTask()
        build_task.context = context_filename

        # Pull out the repository from the dockerfile
        try:
            user, repo = dockerfile.get("REPOSITORY").next().pop().split("/")
            build_task.image.repository.username = user
            build_task.image.repository.repo_name = repo
        except StopIteration:
            raise KeyError("No REPOSITORY found in %s" % path)

        # Pull out the registry from the dockerfile
        try:
            registry = dockerfile.get("REGISTRY").next().pop().split(":")
            build_task.image.registry.hostname = registry[0]
            if len(registry) > 1:
                build_task.image.registry.port = int(registry[1])
        except StopIteration:
            raise KeyError("No REGISTRY found in %s" % path)

        # Pull out the tags from the dockerfile
        build_task.image.tag.extend(map(lambda t: t[0], dockerfile.get("TAG")))

        # Define the mesos task
        task = mesos_pb2.TaskInfo()
        task.name = "build"
        task.task_id.value = task_id
        task.slave_id.value = offer.slave_id.value
        # task.command.value = "pwd"  # Empty value to allow us to use command URIs below

        # uri = task.command.uris.add()
        # uri.value = os.path.join(self.args.staging_uri, staging_context_path)

        task.data = build_task.SerializeToString()
        task.executor.MergeFrom(self.executor)

        # Build up the resources
        cpu_resource = task.resources.add()
        cpu_resource.name = "cpus"
        cpu_resource.type = mesos_pb2.Value.SCALAR
        cpu_resource.scalar.value = self.cpu

        mem_resource = task.resources.add()
        mem_resource.name = "mem"
        mem_resource.type = mesos_pb2.Value.SCALAR
        mem_resource.scalar.value = self.mem

        logger.info("Launching task %s to build %s", task_id, path)

        driver.launchTasks(offer.id, [task])
        self.running += 1

    def _create_filesystem(self, staging_uri, s3_key, s3_secret):
        """Create an instance of a filesystem based on the URI"""

        url = urlparse(staging_uri)

        # Local filesystem
        if not url.scheme:
            return OSFS(
                root_path=url.path,
                create=True
            )

        # S3 filesystem
        if url.scheme.lower() == "s3":
            if not url.netloc:
                raise Exception("You must specify a s3://bucket/ when using s3")
            return S3FS(
                bucket=url.netloc,
                prefix=url.path,
                aws_access_key=s3_key,
                aws_secret_key=s3_secret,
                key_sync_timeout=3
            )

    def _make_build_context(self, output, context_root, dockerfile):
        """Generate and return a compressed tar archive of the build context."""

        tar = tarfile.open(mode="w:gz", fileobj=output)
        for idx, (cmd, instruction) in enumerate(dockerfile.instructions):
            if cmd == "ADD":
                local_path, remote_path = instruction
                tar_path = "context/%s" % str(idx)

                if not local_path.startswith("/"):
                    local_path = os.path.join(context_root, local_path)
                local_path = os.path.abspath(local_path)

                logger.debug("Adding path %s to tar at %s", local_path, tar_path)
                tar.add(local_path, arcname=tar_path)
                dockerfile.instructions[idx] = (cmd, (tar_path, remote_path))

        # Write the modified dockerfile into the tar also
        buildfile = StringIO.StringIO()
        buildfile.write("# Generated by ddocker\n")

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
