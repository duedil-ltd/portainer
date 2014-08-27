
# portainer

Portainer is an [Apache Mesos](http://mesos.apache.org) framework that enables you to build docker images across a cluster of many machines. Given a valid `Dockerfile`, portainer can build your image and push it to a private registry faster than you can count to `n`.

When building docker images at scale, it can be time consuming to manage dedicated infrastructure for building and pushing images. Building large containers with many sources and dependencies is a heavy operation, requiring large machines, and multiple of them.

Given an existing Apache Mesos cluster, portainer can get going right away. If you're new to Mesos, you can try out the Vagrant box provided, or learn more about the [Apache Mesos Architecture](http://mesos.apache.org/documentation/latest/mesos-architecture/) and [get started](http://mesos.apache.org/gettingstarted/).

## Features

- The portainer `Dockerfile` is backwards compatible with standalone `docker build`
- Support for building multiple images at the same time across many machines
- Configurable CPU/Memory limits for image build tasks
- No work required on the mesos slaves if using the [mesos docker integration](http://mesos.apache.org/documentation/latest/docker-containerizer/)

## Getting Started

### Framework Dependencies

You'll need to have the following dependencies installed to run the framework, though it's likely you'll only need to install the ones highlighted in bold;

- Python 2.7
- **Python `virtualenv`**
- **Protocol Buffers (`brew install protobuf`)**
- Make

### Mesos Slave Dependencies

Portainer will launch an ephemeral docker daemon on the, slave configured to work within the mesos sandbox provided. This means the build artifacts left behind by docker (from `docker build`) will be cleaned out automatically by the mesos GC process.

This means the Mesos slave nodes are required to have a `docker` executable installed, though the docker daemon does not need to be running.

##### Docker Containerizer

If you're using the [mesos docker integration](http://mesos.apache.org/documentation/latest/docker-containerizer/) you can specify the `--docker-executor-image` command line flag to specify the image to be used for building inside. If you're happy using a public image, you can use `--docker-executor-image=jpetazzo/dind`

## Building Images

### 1. Upload the mesos executor

Before being able to use portainer, you need to upload the executor code for mesos to launch on the slave nodes. You can build it using `make executor`. If you have any changes locally, the script will exit and warn you before doing anything. The archive will be build into `./dist/` and needs to be uploaded somewhere mesos can reach it (HDFS, S3, FTP, HTTP etc).

Once you've uploaded that to somewhere.. save the full URL for later.

### 2. Write your `Dockerfile`

As mentioned above, the `Dockerfile`s used by portainer are almost identical to those used by docker itself. There are a few extra commands that can be used as metadata for portainer, one of which is required.

*Note: Adding these extra commands will **not** cause the `Dockerfile` to be unusable with the standard `docker build` command. They will simply be ignored.*

- `REGISTRY` - The docker registry to push the image to once built
- `REPOSITORY` - The name of the image repository (i.e `duedil-ltd/portainer`)
- `CPUS` - The number of CPUs required to build the image (a float)
- `MEM` - The amount of memory required to build the image (int, in megabytes)

For an example, take a look at the `Dockerfile` provided in the `./example` folder. This can be used to build an image of the portainer source code.

### 4. Local `ADD` sources

If your `Dockerfile` (like the example provided) contains no `ADD` commands that use local files (`http://` is fine), you can skip this step entirely. If you do use local sources, continue reading.

Docker provides a way of bundling up local sources into the image being built, using the `ADD` command. For example;

```
ADD ./src /usr/lib/my-src
```

Since portainer will build your image on a remote machine, it has the ability to automatically discover these local sources, bundle them up, and upload them with the task. You can use any filesystem supported by [`pyfs`](github.com/duedil-ltd/pyfilesystem), including HDFS and S3. If you're using S3 you will need to configure the correct environment variables for authentication, being `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY`.

Use the `--staging-uri` command line flag to specify this. For example to distribute sources using your HDFS cluster, `--staging-uri=hdfs://my.namenode:50070/tmp/portainer`.

*Note: Portainer imposes no restrictions on symlinks or relative paths in `ADD` commands, unlike docker. In some situations this can pose security issues if building `Dockerfile`s from untrusted sources. Portainer and the mesos executor will only have access to files readable to the user it's running as, so don't run as `root`.*

### 3. Launch portainer

Now that you've got everything set up, you should be good to go. Because portainer uses a pure-python implementation of the Mesos Framework API ([called pesos](http://github.com/wickman/pesos)) there is no requirement to install mesos itself.

```
$ cd portainer
$ ./bin/portainer example/Dockerfile.in \
        --mesos-master "localhost:5050" \
        --executor-uri "hdfs:///path/to/portainer-executor.tar.gz" \
        --tag "latest" \
        --tag "something_else"
```
