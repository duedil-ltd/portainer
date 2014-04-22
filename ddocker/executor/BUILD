
python_library(
    name = 'executor',
    sources = globs("*.py"),
    dependencies = [
        pants('ddocker/util')
    ]
)

python_binary(
    name = 'ddocker_executor',
    dependencies = [
        pants(':executor')
    ],
    entry_point = 'ddocker.executor'
)
