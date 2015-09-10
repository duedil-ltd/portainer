# import logging
import json
import tarfile
import tempfile
import threading
import uuid
from Queue import Queue

import tornado.ioloop
import tornado.web

# from portainer.util.parser import parse_dockerfile_fp


def make_app(queue, staging_fs):
    return tornado.web.Application([
        tornado.web.url(r'/_ping', PingHandler, name='ping'),
        tornado.web.url(r'/v.*/build', BuildHandler, dict(queue=queue, fs=staging_fs), name='build')
    ])


class PingHandler(tornado.web.RequestHandler):
    def get(self):
        self.write("OK")


@tornado.web.stream_request_body
class BuildHandler(tornado.web.RequestHandler):
    """
    """

    def initialize(self, queue, fs):
        self.fs = fs
        self.queue = queue

    def prepare(self):
        self.tmp = tempfile.TemporaryFile()
        self.building = threading.Event()
        self.msg_stream = Queue()

    def data_received(self, data):
        self.tmp.write(data)

    def post(self):
        self.set_header("Content-Type", "application/json")

        try:
            dockerfile_path = self.get_argument("dockerfile", "Dockerfile")
            repository_tag = self.get_argument("t", None)
            verbose = not self.get_argument("q", True)  # TODO: Handle casting to bool?
            build_mem = self.get_argument("memory", 0)
            build_cpu = float(self.get_argument("cpushares", 1))

            if not repository_tag:
                self.set_status(500)
                self._send(err="Missing repository name for the docker image, use -t")
                return
            if not build_mem:
                self.set_status(500)
                self._send(err="No build memory limit set (megabytes)")
                return

            try:
                if verbose:
                    self._send(msg="DEBUG: Opening context")
                self.tmp.seek(0)
                tar = tarfile.TarFile(fileobj=self.tmp)
                if verbose:
                    self._send(msg="Reading Dockerfile from %r" % dockerfile_path)
                tar.extractfile(dockerfile_path)
            except:
                self.set_status(500)
                self._send(err="Failed to load Dockerfile from tar context %r" % dockerfile_path)
                return

            self.set_status(200)
            self._send(msg="Processing submitted build context")

            task_id = str(uuid.uuid1())
            staging_dir = os.path.join("staging", task_id)
            self.fs.makedir(staging_dir, recursive=True)

            self.tmp.seek(0)
            self.building.set()

            staging_context = os.path.join(staging_dir, "context.tar.gz")
            self.filesystem.setcontents_async(
                path=staging_context,
                data=self.tmp,
                progress_callback=partial(
                    self._ctx_upload_progress,
                    task_id,
                    verbose
                ),
                finished_callback=partial(
                    self._ctx_upload_finished,
                    task_id,
                    repository_tag,
                    build_mem,
                    build_cpu,
                    verbose
                ),
                error_callback=partial(
                    self._ctx_upload_failed,
                    task_id,
                    verbose
                )
            )

            self._stream_messages()

        finally:
            self.building.clear()
            self.msg_stream.close()
            self.tmp.close()

    def _send(self, msg=None, err=None):
        if msg and err:
            raise ArgumentError
        if msg:
            self.write(json.dumps({
                "stream": "%s\n" % msg
            }))
            self.flush()
        elif err:
            self.write(json.dumps({
                "error": "%s\n" % err
            }))
            self.flush()

    def _stream_messages(self):
        """
        Wait for the build to finish and stream messages back to the client as
        they appear on the stream.
        """

        while self.building.is_set():
            msg = self.msg_stream.get(True, 0.1)
            if not msg:
                continue

            message, is_error = msg
            if is_error:
                self._send(err=message)
            else:
                self._send(msg=msg)

    def _ctx_upload_progress(self, task_id, verbose, total, bytes):
        """
        Callback for progress updates to the build context upload.
        """

        # TODO: Show some sort of progress information? Perhaps look into how
        # Docker does the streaming progress bars.
        pass

    def _ctx_upload_finished(self, task_id, repository_tag, build_mem, build_cpu, verbose):
        """
        Callback for when the build context upload finishes. When this callback
        is fired, the actual build is placed on the queue with relevant parameters.
        """

        self.msg_stream.put(("Finished uploaded build context", False))

        build_task = portainer_pb2.BuildTask()
        build_task.stream = vebose
        build_task.context = "context.tar.gz"

        repo = parse_repository(repository_tag)
        build_task.image.registry.hostname = repo.registry_host
        if repo.registry_port:
            build_task.image.registry.port = repo.registry_port

        build_task.image.repository = repo.name
        build_task.image.tag.append(repo.tag)

        self.queue.put((build_task, self.building, self.msg_stream))

    def _ctx_upload_failed(self, task_id, verbose, exc):
        """
        Callback for when the build context upload fails.
        """

        self.msg_stream.put(("Caught exception while uploading the build context", True))
        self.building.clear()

        raise exc

    # def on_connection_close(self):
    #     # TODO: Kill any builds in progress
    #     print "YEAH CLOSED"
    #     super(BuildHandler, self).on_connection_close()
