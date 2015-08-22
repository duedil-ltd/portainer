"""The entrypoint to the portainer app. Spins up the a schedular instance and
waits for the result."""

# import getpass
import logging

import pesos.scheduler
from Queue import Queue
from tornado.ioloop import IOLoop
from pesos.vendor.mesos import mesos_pb2
# import sys
import threading
import time

from portainer.app import subcommand
from portainer.api import make_app
from portainer.scheduler import Scheduler

logger = logging.getLogger("portainer.build")


def args(parser):

    parser.add_argument("--executor-uri", dest="executor", required=True,
                        help="URI to the portainer executor for mesos")
    parser.add_argument("--push-registry", required=False,
                        help="Docker registry to push images to")
    parser.add_argument("--container-image", default="jpetazzo/dind",
                        help="Docker image to run the portainer executor in")
    parser.add_argument("--insecure", default=False, action="store_true",
                        help="Enable pulling/pushing of images with insecure registries")
    parser.add_argument("--staging-uri", required=False,
                        help="The URI to use as a base directory for staging files.")
    parser.add_argument("--host", default="0.0.0.0",
                        help="IP address for the API to listen on")
    parser.add_argument("--port", default=3000, type=int,
                        help="Port for the API to listen on")


@subcommand("server", callback=args)
def main(args):

    framework = mesos_pb2.FrameworkInfo()
    framework.user = ""  # Mesos will fill this in
    framework.name = "Portainer Server"

    queue = Queue()

    scheduler = Scheduler(
        task_queue=queue,
        executor_uri=args.executor,
        push_registry=args.push_registry,
        staging_uri=args.staging_uri,
        container_image=args.container_image,
        verbose=args.verbose,
        insecure_registries=args.insecure
    )

    # Spawn the HTTP API
    def start_app():
        application = make_app(queue, scheduler.filesystem)
        application.listen(args.port, args.host)
        logger.info("HTTP API Listening on %s:%d" % (args.host, args.port))
        IOLoop.current().start()

    thread = threading.Thread(target=start_app)
    thread.setDaemon(True)
    thread.start()

    # Spawn the scheduler driver
    driver = pesos.scheduler.PesosSchedulerDriver(
        scheduler, framework, args.mesos_master
    )

    thread = threading.Thread(target=driver.run)
    thread.setDaemon(True)
    thread.start()

    while True:
        time.sleep(0.1)
