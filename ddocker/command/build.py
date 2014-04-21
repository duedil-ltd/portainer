"""
"""

from ddocker import subcommand
from ddocker.proto import ddocker_pb2
from ddocker.proto import mesos_pb2


def args(parser):
    parser.add_argument("dockerfile")


@subcommand("build", callback=args)
def main(args):
    # Launch the mesos framework
    # Parse the dockerfile
    # Re-write the dockerfile with new ADD paths for local files
    # Bundle up the assets and the new dockerfile into the build context
    # Upload the build context to the shared filesystem
    # Create a mesos task and ship it to the framework
        # Download the tar to the sandbox
        # POST /build (stdin = the tar)
        # Tag and push the image
    # Return and BAM. DONE.

    pass
