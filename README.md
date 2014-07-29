
# ddocker

What is *ddocker*? It's an [Apache Mesos](http://mesos.apache.org) framework that enables you to launch remote `docker build` tasks on a large cluster of machines, without having specialised resources for doing intermittent work that have low utilization.

You can use regular `Dockerfile` files with ddocker, you just need to add an extra line so the task knows where to push the image when it's finished building. Including this won't interfere with a plain old `docker build` invocation, it'll just be ignored.

```
REGISTRY my-registry.foo.net
REPOSITORY foo/bar
```

## Getting Started

### Dependencies

You'll need to have the following dependencies installed to compile;

- Python 2.7
- Virtualenv (installed automatically via `easy_install` if it's missing)
- Protocol Buffers (`brew install protobuf`)
- Automake

#### Mesos Slave Dependencies

**Note: For ddocker to work out of the box, you need to be using Mesos+Docker (e.g with [Deimos](https://github.com/mesosphere/deimos)). This isn't a fundamental requirement, and you can use your own docker daemon by using the `--docker-host` command line argument.**

## Building Images

### 1. Upload the executor

Use the `bin/build-executor` script to generate an executor tar, it'll be put into `dist/`. If you have any changes locally, the script will exit and warn you before doing anything.

Once you've uploaded that to somewhere mesos can get to it... save the full URI for later.

### 2. Write your `Dockerfile`

As mentioned above, the `Dockerfile`s used by ddocker are almost identical to those used by docker itself. However, ddocker introduces a couple of new commands that are required, adding these **will not** cause the `Dockerfile` to be unusable with the standalone `docker build` tool, they will be skipped and ignored.

- `REGISTRY` - The docker registry to push the image to once built
- `REPOSITORY` - The name of the image repository (i.e `tarnfeld/ddocker`)

### 3. Launch ddocker

Now that you've got everything set up, you should be good to go. Because ddocker uses a pure-python implementation of the Mesos API there's no complex dependencies to install. The `bin/setup` script will do it all for you.

**Note: ** The following example assumes you have the `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` environment variables set, if not, you'll need to use the `--aws-*` command line options.

```shell
$ ./bin/ddocker --mesos-master="1.2.3.4:5050" build --executor-uri hdfs:///mesos/ddocker-XXXX.tar.gz --staging-uri s3://my-bucket/ddocker path/to/Dockerfile
```
