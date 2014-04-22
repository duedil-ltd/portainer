"""
Simple parser for Dockerfile's.
"""


def parse_dockerfile(path):
    """Parse a dockerfile and return a new Dockerfile object"""

    dockerfile = Dockerfile()
    with open(path) as f:
        line_buf = ""
        for line in f:
            if line.lstrip().startswith("#") or len(line.rstrip()) == 0:
                continue

            line_buf += line

            if line_buf.endswith("\\"):
                continue

            line_buf = line_buf.rstrip().rstrip("\\")

            dockerfile += line_buf
            line_buf = ""

    return dockerfile


class Dockerfile(object):

    def __init__(self, lines=[]):
        self.instructions = []

        for line in lines:
            self.add_instruction(line)

    def __iadd__(self, instruction):
        self.add_instruction(instruction)
        return self

    def add_instruction(self, instruction):
        parts = instruction.split(" ")
        command = parts[0].upper()
        arguments = parts[1:]

        self.instructions.append((command, arguments))

    def get(self, filter_command):
        for command, instruction in self.instructions:
            if command == filter_command:
                yield instruction
