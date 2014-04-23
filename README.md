
# ddocker [WIP]

**Distributed Docker** is a handy CLI tool for building a docker container on an [Apache Mesos](mesos.apache.org) Cluster.

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

The make command above will generate an executable inside the `dist/` folder. This is ddocker.

## Building Images

### 1. Upload the executor

To enable mesos to build the image and interact with ddocker you'll need to upload the build `dist/ddocker.pex` file somewhere mesos can get to it. This could either be on each slave, in S3 or HDFS. Once you've done that, specify the path using the `--executor-uri` argument.

### 2. Write your Dockerfile.in

The dockerfiles used by ddocker are almost identical functionally to those used by docker itself. However, ddocker introduces three new build commands that are required, adding these **will not** cause the `Dockerfile` to be unusable with the standalone `docker build`, they will be skipped and ignored.

- `REGISTRY` - The docker registry to push the image to once built
- `REPOSITORY` - The name of the image repository (i.e `tarnfeld/ddocker`)
- `TAG` - You can specify any number of `TAG` commands to tag the image with multiple tags

### 3. Launch ddocker

After building ddocker, the `pex` executable files in `dist/` are good to go, they are fully transferable (so long as it's the same machine architecture). The `example` directory contains a `Dockerfile.in` template ready to build with ddocker, simply run the commands below to build a docker image containg this `ddocker/` repository folder.

**Note: ** The following example assumes you have the `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` environment variables set, if not, you'll need to use the `--aws-*` command line options.

```shell
$ ./dist/ddocker.pex build example/Dockerfile.in --executor-uri s3://my-bucket/ddocker.pex --staging-uri s3://my-bucket/ddocker
```
