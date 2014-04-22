
python_library(
    name = 'executor',
    sources = globs("*.py"),
    dependencies = [
        pants('third_party:mesos'),
        pants('third_party:docker-py'),
        pants('src/ddocker/util'),
        pants('src/ddocker/proto')
    ]
)

python_binary(
    name = 'ddocker_executor',
    dependencies = [
        pants(':executor')
    ],
    entry_point = 'ddocker.executor.__main__'
)
