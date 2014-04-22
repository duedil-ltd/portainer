
# ddocker [WIP]

**Distributed Docker** is a handy CLI tool for building and running docker containers on an [Apache Mesos](mesos.apache.org) Cluster. The *running* aspect is aimed only at launching a single short-lived container to run a script/tool somewhere on the cluster.

## Building ddocker

### Dependencies

You'll need to have the following dependencies installed to compile;

- Python 2.7
- Protocol Buffers (`brew install protobuf`)
- Automake

### Compiling with `make`

Building ddocker is easy, it uses the [pants](pantsbuild.github.io) build system from Twitter, and compiles into encapsulated [Python Executables](pex.readthedocs.org).

```shell
$ make dist
```

## Building Images

After building ddocker, the `pex` executable files in `dist/` are good to go, they are fully transferable (so long as it's the same machine architecture). The `example` directory contains a `Dockerfile.in` template ready to build with ddocker, simply run the commands below to build a docker image containg this `ddocker/` repository folder.

**Note: ** The following example assumes you have the `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` environment variables set, if not, you'll need to use the `--aws-*` command line options.

```shell
$ ./dist/ddocker.pex build example/Dockerfile.in --staging-uri s3://my-bucket/ddocker
...
```
