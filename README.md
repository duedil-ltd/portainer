
# Portainer

Portainer is an [Apache Mesos](https://mesos.apache.org) framework that enables you to build Docker images across a cluster of many machines.

```
                   .,.,.,.,.,.,.,.,.,.,.,.,.,.,.,.,.,.,.,.,.,.
                   ,                          .,
                  `,                          ,.
                  ,`                          .,     _        _
               ``.,                 _ __   ___,._ __| |_ __ _(_)_ __   ___ _ __
           `. ``.,.`..             | '_ \ / _ \| '__| __/ _` | | '_ \ / _ \ '__|
   .`.```  ...``..`   ```` `.`     | |_) | (_) | |  | || (_| | | | | |  __/ |
 ...........,`.`............,      | .__/ \___/|_|   \__\__,_|_|_| |_|\___|_|
           ,  `  .```.````.`,      |_| ,.,.,.,.,.,.,.,,.,.,.,.,.,.,.,.,.,.,.,.,.,.,.,
           ,   , `                     ,              ,              ,              ,
           , .`` `                     ,              ,              ,              ,
           , .   `                     ,.,.,.,.,.,.,.,,.,.,.,.,.,.,.,.,.,.,.,.,.,.,.,
           , .   `                     ,              ,              ,              ,
           , .   `                     ,              ,              ,              ,
     .`.,,,,,,,,,..                    ``````````````````````````````````````````````
           `     ,
           ```````
```

When building Docker images at scale, it can be time consuming and wasteful to manage dedicated infrastructure for building and pushing images. Building large containers with many sources and dependencies is a heavy operation, sometimes requiring many large machines. Deploying this infrastructure can be expensive and often leads to poor utilization.

Given an existing Apache Mesos cluster, Portainer can get to work right away. If you're new to Mesos, you can try out the Vagrant box provided, or learn more about the [Apache Mesos Architecture](https://mesos.apache.org/documentation/latest/mesos-architecture/) and [get started](https://mesos.apache.org/gettingstarted/).

See below for more documentation on how to use the Vagrant virtual machine.

--------------------------------------------------------------------------------

## Features

- Works out of the box with existing `Dockerfile` files
- Configurable CPU/Memory resource limits for build tasks
- Full support for all `Dockerfile` commands, including local sources (e.g `ADD ./src`)
- Docker build logs are streamed from the Mesos agent for easy debugging and monitoring
- Support for the `.dockerignore` file

#### Notes

- Pushing built images to the public Docker index is currently not supported

--------------------------------------------------------------------------------

## The Basics

### Dependencies

You'll need to have the following dependencies installed to run the framework.

- Python 2.7
- Python `virtualenv` and `pip`
- Protocol Buffers (`brew install protobuf`)
- Make

### Mesos Agent Dependencies

By default, Portainer will try and launch an ephemeral Docker daemon (`docker -d`) on the mesos agent machine using [docker in docker](https://github.com/jpetazzo/dind). This requires that you're using a Docker Containerizer on your Mesos agents. If you are not, you'll need to specify the `--docker-host` argument (e.g `--docker-host /var/run/docker.sock`) describing where the Docker daemon can be accessed on each agent.

## Building an Image

#### 1. Build/Upload the Executor

```
$ bin/build-executor
```

This script uses PEX to package portainer's code into an executable to be run on Mesos.

_Note: If you've got a dirty git tree, you'll need to set the `FORCE=1` environment variable._

The built PEX (python executable) archive will be dumped into `./dist`, and needs to be uploaded somewhere Mesos can reach it (HDFS, S3, FTP, HTTP etc). Check the output from the build-executor command to see the file name, and upload the file.

The environment name is tacked on to the archive filename, e.g. `dist/portainer-37cc6d5eb334473fdaa9c7522c4ce585032dca5c.linux-x86_64.tar.gz`. Make sure you build the executor on the same platform as your mesos slaves use.

In future, readily-downloadable prebuilt pex files will be available on versioned github releases.

#### 2. Grab a `Dockerfile`

Portainer can work out of the box on any existing `Dockerfile`. A few simple examples can be found in the `example/` directory, or you can build an image of the Portainer framework itself using the one at the root of this project directory.

#### 3. Local sources

If your `Dockerfile` does not include any local sources in the image (via `ADD` or `COPY`) you can skip this step.

Since Portainer will build your image on a remote machine, it must bundle and upload these local sources so they to be used remotely. Portainer uses a staging filesystem that can be accessed both by the framework and by the slave, this can be anything supported by the Mesos Fetcher (e.g HDFS).

Use the `--staging-uri` command line flag to specify this. For example to distribute sources using your HDFS cluster, `--staging-uri=hdfs://my.namenode/tmp/portainer`.

#### 4. Invoke Portainer

Given Portainer is an Apache Mesos framework, we need to define the resources we'd like to use to build our image. The CPU and RAM limits can be specified using the `--build-cpu` and `--build-mem` command line options. We also need to give our image a name (the repository), a tag and specify a registry to push to.

If you'd like to see the STDOUT/STDERR logs from your build printed live, add `--stream` to the list of arguments.

```
$ cd portainer
$ ./bin/portainer \
        --mesos-master "localhost:5050" \
        --executor-uri "hdfs://my-namenode/path/to/portainer-executor.tar.gz" \
        build \
        --staging-uri "hdfs://my-namenode/tmp/portainer" \
        --tag "latest" \
        --to "my-registry:5000" \
        --build-cpu 1 \
        --build-mem 256 \
        ./Dockerfile
```

## Vagrant Example

The vagrant virtual environment provided will launch a VM will the following components for testing out Portainer;

- Mesos Master + Agent + ZooKeeper
- Docker Registry
- Mesos <> Docker Containerizer
- Portainer code

### 1. Start the VM

To use the Vagrant box, run `vagrant up` to set everything up. This will download a Debian 8 virtualmachine and install all the required processes/dependencies.

### 2. Test Mesos

The VM runs on a static IP `192.168.33.50` so before proceeding it's best to check that the Mesos UI is fully up and running at http://192.168.33.50:5050/ and there's a slave joined with at least 256MB of RAM. You should also check that the docker registry is up, a simple `docker ps` should demonstrate this.

### 3. Build the executor

To build the Portainer executor, simply run `bin/build-executor` from the portainer root directory (`/opt/portainer`).

_Note: If you've got a dirty git tree, you'll need to set the `FORCE=1` environment variable._

### 4. Example build

You'll need to fill in a few blanks in the follow command line invocation, but this should start a simple build on the local mesos cluster, and push the image to the local repository.

```
$ bin/portainer \
    --mesos-master 192.168.33.50:5050 \
    build \
    --staging-uri /tmp \
    --executor-uri `pwd`/dist/portainer-{CHANGE THIS TO THE ACTUAL FILE}.tar.gz \
    --to 192.168.33.50:5000 \
    --build-cpu 0.1 \
    --build-mem 256 \
    --repository tarnfeld/portainer \
    --tag latest \
    --stream \
    ./Dockerfile
```
