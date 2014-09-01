"""
Simple parser for Dockerfile's.
"""

import re


def parse_dockerfile(path, variables={}):
    """Parse a dockerfile and return a new Dockerfile object"""

    dockerfile = Dockerfile(variables=variables)
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

    This model also introduces support for variables into the Dockerfile
    syntax. These can be referenced using %% signs. The variables will then
    be replaced with their respective value passed in to the constructor
    of the Dockerfile instance.
    """

    INTERNAL = ["REGISTRY", "REPOSITORY", "BUILD_CPU", "BUILD_MEM"]

    def __init__(self, lines=[], variables={}):
        self.instructions = []
        self.variables = variables

        self.build_cpu = None
        self.build_mem = None
        self.repository = None
        self.registry = None

        for line in lines:
            self.add_instruction(line)

    def __iadd__(self, instruction):
        self.add_instruction(instruction)
        return self

    def replace_variables(self, line):
        # Find all variables in the line
        for match in re.finditer(r'%([A-z_]+)%', line):
            if not match.group(1).endswith("\\"):
                key = match.group(1).lower()
                if key not in self.variables:
                    raise Exception("Variable %%%s%% not defined" % (key))
                line = line[:match.start()] + self.variables[key] + line[match.end():]
        return line

    def add_instruction(self, instruction):
        parts = instruction.split(" ")
        command = parts[0].upper()
        arguments = [self.replace_variables(a) for a in parts[1:]]

        self.instructions.append((command, arguments))

        if command.lower() in self.INTERNAL:
            setattr(self, command.lower(), arguments)

    def get(self, filter_command, default=None):
        for command, instruction in self.instructions:
            if command == filter_command:
                yield instruction
                break
        else:
            if filter(None, default):
                yield default
