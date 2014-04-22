
python_library(
    name = 'app',
    sources = globs("*.py"),
    dependencies = [
        pants('third_party:fs'),
        pants('third_party:boto'),
        pants('third_party:progressbar'),
        pants('third_party:mesos'),
        pants('src/ddocker/util'),
        pants('src/ddocker/proto')
    ]
)

python_binary(
    name = 'ddocker',
    dependencies = [
        pants(':app')
    ],
    entry_point = 'ddocker.app.__main__'
)
