# import logging
import json
import tempfile
import tarfile

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

    def data_received(self, data):
        self.tmp.write(data)

    def post(self):
        self.set_header("Content-Type", "application/json")

        try:
            dockerfile_path = self.get_argument("dockerfile", "Dockerfile")
            repository_tag = self.get_argument("t", None)
            verbose = self.get_argument("q", True)
            build_mem = self.get_argument("memory", 0)
            build_cpu = float(self.get_argument("cpushares", 1))

            if not repository_tag:
                self.set_status(500)
                self._send(error="Missing repository name for the docker image, use -t")
                return
            if not build_mem:
                self.set_status(500)
                self._send(error="No build memory limit set (megabytes)")
                return

            try:
                self.tmp.seek(0)
                tar = tarfile.TarFile(fileobj=self.tmp)
                raw_dockerfile = tar.extractfile(dockerfile_path)
            except:
                self.set_status(500)
                self._send(error="Failed to load Dockerfile from tar context %r" % dockerfile_path)
                return

            self.set_status(200)
            self._send(message="Processing submitted build context")

            # Parse the Dockerfile to ensure it's valid
            # try:
            #     parse_dockerfile_fp(raw_dockerfile)
            # except:
            #     self._send(error="Failed to parse Dockerfile")

            # TODO: Create a staging directory for the build tar
            # TODO: Upload the build tar
            # TODO: Queue the build and watch for logs to be streamed back from the scheduler
            # TODO: Handle killing the build if the connection is lost to the client
        finally:
            self.tmp.close()

    def _send(self, message=None, error=None):
        if message:
            self.write(json.dumps({
                "stream": "%s\n" % message
            }))
            self.flush()
        elif error:
            self.write(json.dumps({
                "error": "%s\n" % error
            }))
            self.flush()

    # def on_connection_close(self):
    #     # TODO: Kill any builds in progress
    #     print "YEAH CLOSED"
    #     super(BuildHandler, self).on_connection_close()
