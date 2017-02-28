"""The scheduler. Communicates with mesos to listen for offers; then prepare
the task definition; pack up the task context; ship it to the staging area;
accept the offer and launch the task; and wait for the result"""

import base64
import logging
import os
import progressbar
import pymesos
import sys
import tarfile
import tempfile
import threading
import traceback
import uuid

from Queue import Queue
from collections import defaultdict
from functools import partial
from urlparse import urlparse

from fs.opener import opener
from fnmatch import fnmatch

from portainer.proto import portainer_pb2
from portainer.util.parser import parse_dockerfile, parse_dockerignore

logger = logging.getLogger("portainer.scheduler")


class TaskContextException(Exception):
    pass


class StagingSystemRequiredException(Exception):
    pass


class Scheduler(pymesos.Scheduler):

    def __init__(self, executor_uri, cpu_limit, mem_limit, push_registry,
                 staging_uri, stream=False, verbose=False, repository=None,
                 pull_registry=None, docker_host=None, container_image=None,
                 insecure_registries=False, max_retries=3):

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
        self.container_image = container_image
        self.insecure_registries = insecure_registries
        self.max_retries = max_retries

        self.pending = 0
        self.running = 0
        self.finished = 0
        self.failed = 0
        self.queued_tasks = []
        self.task_status = defaultdict(lambda: None)
        self.task_history = {}
        self.task_retries = defaultdict(int)
        self.blacklist = set()

        self._processing_offers = threading.Lock()
        self._processing_queue = threading.Lock()

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

        self.cleanup = TaskCleanupThread(self.filesystem)
        self.cleanup.start()

    def enqueue_build(self, path, tags):
        """Enqueue a dockerfile (with a set of associated tags) to build.
        """

        task_id = str(uuid.uuid1())
        logger.info("Queuing build for %s for %s", task_id, path)

        build_task = portainer_pb2.BuildTask()
        build_task.stream = self.stream
        build_task.task_id = task_id

        dockerfile = parse_dockerfile(path, registry=self.pull_registry)

        # Prepare a custom build context if there are any local sources, since they
        # will need to be shipped to the cluster
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
            build_task.context_url = os.path.join(self.staging_uri, staging_context_path)
        else:
            build_task.dockerfile = dockerfile.build()

        # Configure properties on the docker daemon
        if self.docker_host:
            build_task.daemon.docker_host = self.docker_host
        if self.insecure_registries:
            for registry in [self.pull_registry, self.push_registry]:
                if registry:
                    build_task.daemon.insecure_registries.append(registry)

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
            raise ValueError("Failed to parse REGISTRY in %s" % path)

        # Add any tags
        build_task.image.tag.extend(tags)

        with self._processing_queue:
            self.pending += 1
            self.queued_tasks.append((dockerfile, build_task))

    def _make_build_context(self, output, context_root, dockerfile):
        """Generate and return a compressed tar archive of the build context."""

        if not self.filesystem:
            raise StagingSystemRequiredException("A staging filesystem is required for local sources")

        tar = tarfile.open(mode="w:gz", fileobj=output)
        for idx, (cmd, instruction) in enumerate(dockerfile.instructions):
            if cmd in ("ADD", "COPY"):
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

    def statusUpdate(self, driver, status):
        """Called when a status update is received from the mesos cluster."""

        finished = False
        failed = False
        task_id = status['task_id']['value']

        if status['task_id']['value'] not in self.task_history:
            logger.error("Task update for unknown task! %s", task_id)
            return

        if status['state'] == 'TASK_STARTING':
            logger.info("Task update %s : STARTING", task_id)
        if status['state'] == 'TASK_RUNNING':
            logger.info("Task update %s : RUNNING", task_id)
        if status['state'] == 'TASK_FAILED':
            logger.info("Task update %s : FAILED", task_id)
            if status['message'] and status.get('data'):
                logger.info("Exception caught while building image: \n\n%s", base64.b64decode(status['data']))
            elif status['message']:
                logger.info("Failure while building image: \n\n%s", status['message'])
            failed = True
        elif status['state'] == 'TASK_FINISHED':
            logger.info("Task update %s : FINISHED", task_id)
            finished = True
        elif status['state'] == 'TASK_KILLED':
            logger.info("Task update %s : KILLED", task_id)
            failed = True
        elif status['state'] == 'TASK_LOST':
            logger.info("Task update %s : LOST", task_id)
            failed = True

        # Update the last known status of the task
        last_known_state = self.task_status[task_id]
        self.task_status[task_id] = status['state']

        if finished:
            self.cleanup.schedule_cleanup(task_id)

            self.running -= 1
            self.finished += 1
        elif failed:
            self.running -= 1

            # Re-queue the task if it hasn't started RUNNING yet
            if last_known_state in {None, 'TASK_STARTING', 'TASK_STAGING'} and \
                            self.task_retries[task_id] < self.max_retries:
                self._reschedule_task(task_id, blacklist_slave=status['agent_id']['value'])
            else:
                self.failed += 1
                self.cleanup.schedule_cleanup(task_id)

        # If there are no tasks running, and the queue is empty, we should stop
        if self.running == 0 and self.pending == 0:
            driver.stop()

    def _reschedule_task(self, task_id, blacklist_slave=None):
        if task_id not in self.task_history:
            logger.error("Cannot re-schedule unknown task %s", task_id)
            return

        with self._processing_queue:
            del self.task_status[task_id]

            self.pending += 1
            self.task_retries[task_id] += 1

            if blacklist_slave:
                self.blacklist.add(blacklist_slave)

            self.queued_tasks.append(self.task_history[task_id])
            logger.info("Re-scheduling task [%d] %s, excluding slave %s",
                        self.task_retries[task_id], task_id, blacklist_slave)

    def registered(self, driver, frameworkId, masterInfo):
        host = masterInfo['hostname'] or masterInfo['ip']
        master = "http://%s:%s" % (host, masterInfo['port'])
        logger.info("Framework %s registered to %s", frameworkId['value'], master)

    def disconnected(self, driver):
        logger.warning("Framework disconnected from the mesos master")

    def reregistered(self, driver, masterInfo):
        host = masterInfo['hostname'] or masterInfo['ip']
        master = "http://%s:%s" % (host, masterInfo['port'])
        logger.info("Framework re-registered to %s", master)

    def error(self, driver, message):
        logger.error("Framework error: %s", message)

    def frameworkMessage(self, driver, executorId, slaveId, message):
        message = base64.b64decode(message)
        if "Buffering" in message:  # Heh. This'll do for now, eh?
            logger.debug("\t%s", message)
        else:
            logger.info("\t%s", message)

    def resourceOffers(self, driver, offers):
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
        with self._processing_offers:
            tasks_to_launch = []

            if not self.pending:
                driver.declineOffer([offer['id'] for offer in offers])
            else:
                for offer in offers:
                    offer_cpu = 0.0
                    offer_mem = 0
                    offer_role = None

                    # Extract the important resources from the offer
                    for resource in offer['resources']:
                        offer_role = resource['role']
                        if resource['name'] == "cpus":
                            offer_cpu = float(resource['scalar']['value'])
                        if resource['name'] == "mem":
                            offer_mem = int(resource['scalar']['value'])

                    logger.debug("Received offer for cpus:%f mem:%d role:%s", offer_cpu, offer_mem, offer_role)

                    # Look for a task in the queue that fits the bill
                    with self._processing_queue:
                        if offer['agent_id']['value'] in self.blacklist:
                            logger.info("Ignoring offer from blacklisted agent %s", offer['agent_id']['value'])
                            driver.declineOffer(offer['id'])
                            continue

                        for idx, (dockerfile, build_task) in enumerate(self.queued_tasks):
                            cpu = float(dockerfile.get("BUILD_CPU", [self.cpu]).next()[0])
                            mem = int(dockerfile.get("BUILD_MEM", [self.mem]).next()[0])

                            if cpu <= offer_cpu and mem <= offer_mem:
                                # Remove the task from the queue, we set this to None
                                # to avoid changing the size of the list while looping
                                self.queued_tasks[idx] = None
                                self.pending -= 1
                                self.running += 1
                                tasks_to_launch.append((offer, offer_role, cpu, mem, dockerfile, build_task))
                                logger.info("Launching build task %s with offer from %s", build_task.task_id, offer['hostname'])
                                break  # TODO: Don't currently support launching multiple tasks in a single offer
                        else:
                            logger.debug("Ignoring offer %r", offer)
                            driver.declineOffer(offer['id'])

                        # Remove all of the tasks that are about to be launched
                        self.queued_tasks = filter(None, self.queued_tasks)

        # Launch the build tasks on the mesos cluster
        # We do this outside of the _processing_offers lock because if there are
        # any tasks, we've already taken them off the queue to be launched.
        for offer, role, cpu, mem, dockerfile, build_task in tasks_to_launch:
            try:
                tasks = [self._prepare_task(
                    driver=driver,
                    dockerfile=dockerfile,
                    build_task=build_task,
                    offer=offer,
                    cpu=cpu,
                    mem=mem,
                    role=role
                )]
            except Exception, e:
                logger.error("Caught exception: %s", e.message)
                self.failed += 1
                self.running -= 1
                tasks = []

            if tasks:
                driver.launchTasks([offer['id']], tasks)
            else:
                driver.declineOffer([offer['id']])

    def _prepare_task(self, driver, dockerfile, build_task, offer, cpu, mem, role):

        # Define the mesos task
        task = {}
        task['name'] = "%s/%s" % (":".join([build_task.image.registry.hostname, str(build_task.image.registry.port)]), build_task.image.repository)
        task['task_id'] = {
            'value': build_task.task_id
        }
        task['agent_id'] = {
            'value': offer['agent_id']['value']
        }

        # Create the executor
        args = []
        if self.verbose:
            args.append("--verbose")

        task['executor'] = {
            'executor_id': {
                'value': build_task.task_id
            },
            'command': {
                'value': "${MESOS_SANDBOX:-${MESOS_DIRECTORY}}/%s/bin/portainer %s run-executor"
                         % (os.path.basename(self.executor_uri).rstrip(".tar.gz"), " ".join(args))
            }
        }

        if self.container_image:
            task['executor']['container'] = {
                'type': 'DOCKER',
                'docker': {
                    'image': self.container_image,
                    'privileged': True
                }
            }

        task['executor']['name'] = "build"
        task['executor']['source'] = "build %s" % (task['name'])

        # Configure the mesos executor with the portainer executor uri
        task['executor']['command']['uris'] = [
            {
                'value': self.executor_uri
            }
        ]

        if build_task.context:
            # Add the docker context
            task['executor']['command']['uris'].append({
                'value': build_task.context_url,
                'extract': False
            })

        task['data'] = base64.b64encode(build_task.SerializeToString())
        task['executor']['data'] = task['data']

        # Build up the resources we require
        cpu_resource = {
            'name': "cpus",
            'type': 'SCALAR',
            'role': role,
            'scalar': {
                'value': cpu
            }
        }

        mem_resource = {
            'name': "mem",
            'type': 'SCALAR',
            'role': role,
            'scalar': {
                'value': mem
            }
        }

        task['resources'] = [
            cpu_resource,
            mem_resource
        ]

        self.task_history[build_task.task_id] = (dockerfile, build_task)

        return task


class TaskCleanupThread(threading.Thread):

    def __init__(self, fs, *args, **kwargs):
        self.filesystem = fs

        self._queue = Queue()
        self._queue_event = threading.Event()

        super(TaskCleanupThread, self).__init__(*args, **kwargs)

        self.setDaemon(True)

    def schedule_cleanup(self, task_id, attempt=0):

        if not self.filesystem:
            logging.info("Skipping cleanup due to no filesystem")
            return

        logger.debug("Scheduling cleanup for task %s", task_id)

        self._queue.put((task_id, attempt))
        self._queue_event.set()

    def run(self):

        while True:
            self._queue_event.wait()
            task_id, attempts = self._queue.get()

            if attempts > 2:
                logger.error("Failed to cleanup staging directory after %d attempts", attempts + 1)
                self._queue.task_done()

            staging_dir = os.path.join("staging", task_id)
            logger.info("Cleaning up staging directory %s", staging_dir)

            try:
                if self.filesystem.isdir(staging_dir):
                    self.filesystem.removedir(staging_dir, force=True)
                else:
                    logger.info("Skipping cleanup of directory %s as it doesn't exist", staging_dir)
                self._queue.task_done()
            except Exception, e:
                logger.error("Caught exception cleaning staging directory %s (%s)", staging_dir, e)
                self.schedule_event(task_id, attempts + 1)
