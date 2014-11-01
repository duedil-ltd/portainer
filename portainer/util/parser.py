"""
Simple parser for Dockerfile's.
"""


def parse_dockerfile(path, **kwargs):
    """Parse a dockerfile and return a new Dockerfile object"""

    dockerfile = Dockerfile(**kwargs)
    with open(path) as f:
        line_buf = ""
        for line in f:
            if line.lstrip().startswith("#") or len(line.rstrip()) == 0:
                continue

            line_buf += line

            if line.rstrip().endswith('\\'):
                continue

            line_buf = line_buf.rstrip().rstrip("\\")

            dockerfile += line_buf
            line_buf = ""

    return dockerfile


def parse_dockerignore(ignore_file):
    """Return a generator of glob patterns to ignore."""

    for line in ignore_file:
        line = line.strip()
        if line and not line.startswith("#"):
            yield line


class Dockerfile(object):
    """Model to represent a parse Dockerfile.

    Instructions (aka lines) are parsed into two components, a command and
    a list of values. For example...

    `RUN apt-get update foo`
     -> command: RUN
     -> values: [apt-get, update, foo]

    Commands that are internal to portainer and not part of the standard
    Dockerfile spec are listed in the INTERNAL class constant. When an
    instruction containing and internal command is added, the value is
    assigned as a property on this object.

    It's always useful to remember that instruction values are always lists.

    If the `registry` parameter is present, any FROM instructions will be
    modified to pull images from the given registry. For example...

    `FROM foo/bar`
     -> This will be pulled from `{registry}/foo/bar`
    `FROM ubuntu`
     -> This will be pulled from `{registry}/ubuntu`
    """

    INTERNAL = ["REGISTRY", "REPOSITORY", "BUILD_CPU", "BUILD_MEM"]

    def __init__(self, lines=[], registry=None):
        self.instructions = []
        self.registry = registry

        self.build_cpu = None
        self.build_mem = None
        self.repository = None

        for line in lines:
            self.add_instruction(line)

    def __iadd__(self, instruction):
        self.add_instruction(instruction)
        return self

    def add_instruction(self, instruction):
        parts = instruction.split(" ")
        command = parts[0].upper()
        arguments = parts[1:]

        if command == "FROM" and self.registry:
            parts = arguments[0].split("/")
            if len(parts) <= 2:
                parts[:0] = [self.registry]
                arguments = ["/".join(parts)]

        self.instructions.append((command, arguments))

        if command.lower() in self.INTERNAL:
            setattr(self, command.lower(), arguments)

    def get(self, filter_command, default=[]):
        for command, instruction in self.instructions:
            if command == filter_command:
                yield instruction
                break
        else:
            if filter(None, default):
                yield default

    @property
    def has_local_sources(self):
        return len(
            filter(
                lambda (src, dst): not src.startswith("http"),
                self.get("ADD")
            )
        ) > 0

    def build(self):
        return "\n".join([" ".join([i[0]] + i[1]) for i in self.instructions])
