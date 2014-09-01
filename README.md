
# Portainer

Portainer is an [Apache Mesos](http://mesos.apache.org) framework that enables you to build docker images across a cluster of many machines. Given a valid `Dockerfile`, Portainer can build your image and push it to a private registry faster than you can count to `n`.

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
           ```````                               ,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,
````````````````````````````````                 \
                               |¸.·´¯`·.´¯`·.¸¸.·´\     o    o    o    o    o    o
                               |                   \
    __|___|___|___|___|___|    |                    \................................
       |___|___|___|___|       |   (
         ___|___|___|___|      |    )  (      _/|_/       |  |
      |___|___|___|            |   (    )    <').-\        \/        Y
                               |    )  (     ``            |  /!-!\  |
                               |   (    )                   \|     |/
                               |    )  (                     _\___/_
                               |   (    )                   / /   \ \
```

When building docker images at scale, it can be time consuming and wasteful to manage dedicated infrastructure for building and pushing images. Building large containers with many sources and dependencies is a heavy operation, requiring large machines, and multiple of them. Deploying this infrastructure can be expensive and lead to poor utilization.

Given an existing Apache Mesos cluster, Portainer can get to work right away. If you're new to Mesos, you can try out the Vagrant box provided, or learn more about the [Apache Mesos Architecture](http://mesos.apache.org/documentation/latest/mesos-architecture/) and [get started](http://mesos.apache.org/gettingstarted/).

**Note: If you are _not_ using the External Containerizer + Docker integration (with [our containerizer](http://github.com/duedil-ltd/mesos-docker-containerizer)/[deimos](https://github.com/mesosphere/deimos)) this framework will not work for you as it stands. This also goes for the docker containerizer released in 0.20.0 as it does not support the `--privileged` option.**

--------------------------------------------------------------------------------

## Features

- Works out of the box with existing `Dockerfile` files
- Configurable CPU/Memory resource limits for build tasks
- Full support for all `Dockerfile` commands, including local sources (e.g `ADD ./src`)
- Capable of building many images in parallel across the cluster
- Docker build logs are streamed from the Mesos slave for easy debugging and monitoring

#### Not Supported

- Pushing built images to the public docker index

--------------------------------------------------------------------------------

## Getting Started

### Framework Dependencies

You'll need to have the following dependencies installed to run the framework, though it's likely you'll only need to install the ones highlighted in bold;

- Python 2.7
- **Python `virtualenv`**
- **Protocol Buffers (`brew install protobuf`)**
- Make

## Building Images

#### 1. Upload the Mesos executor

**Note: If the version of Portainer you are using is available as a [github release](http://github.com/duedil-ltd/portainer/releases) you can skip this step and use the github URL.**

Before being able to use Portainer, you need to upload the executor code somewhere accessible by the Mesos slaves. You can build a tar archive using `make executor`. The archive will be dumped into `./dist/` and needs to be uploaded somewhere Mesos can reach it (HDFS, S3, FTP, HTTP etc).

#### 2. Write your `Dockerfile`

Portainer can work out of the box on existing `Dockerfile` files with no modifications. To do this, you _must_ specify a repository for your image, using the `--repository` command line argument, for example`--repository duedil/portainer`.

You must also specify a private registry to push the image to once successfully built, using the `--to` command line argument, for example `--to my.registry:1234`.

If your `Dockerfile` is based upon a private image (in the `FROM` instruction) not available in the public docker index, you can use the `--from my.registry:1234` argument to configure where dependent images are pulled from. It is worth noting that when `--from` is used, all images are pulled from the given registry, and the public index is **never** used. This can be useful for mirroring public images which avoids being dependent on the public index.

Since Mesos is based around the concept of _Resources_, build tasks need some CPU and Memory to be able to execute. Defaults are provided, but the `--build-cpu` and `--build-mem` command line flags can be used to configure the resource allocation used.

--------------------------------------------------------------------------------

As mentioned above, Portainer supports a set of custom `Dockerfile` instructions. These are safe to use with the standard `docker build` tool as they will simply be ignored.

- `REPOSITORY`  / `--repository` - The name of the image repository (`string`)
- `BUILD_CPU`   / `--build-cpu` - The number of CPUs required to build the image (`float`)
- `BUILD_MEM`   / `--build-mem` - The amount of memory required to build the image (`integer`, in megabytes)

For an example, take a look at the `Dockerfile` provided in the `./example` folder. This can be used to build an image of the Portainer source code.

#### 3. Local `ADD` sources

If your `Dockerfile` does not container any `ADD` commands that use local files, you can skip this step entirely. If you do use local sources, continue reading. Additional configuration is required.

Docker provides a way of bundling up local sources into the image being built, using the `ADD` command. For example;

```
ADD ./src /usr/lib/my-src
```

Since Portainer will build your image on a remote machine, it has to bundle and upload these local sources, so they to be used remotely when building the image. You can use any filesystem supported by [`pyfs`](github.com/duedil-ltd/pyfilesystem), including HDFS and S3. If you're using S3 you will need to configure the correct environment variables for authentication, being `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY`.

Use the `--staging-uri` command line flag to specify this. For example to distribute sources using your HDFS cluster, `--staging-uri=hdfs://my.namenode:50070/tmp/portainer`.

*Note: Portainer imposes no restrictions on symlinks or relative paths in `ADD` instructions, unlike docker. In some situations this can pose security issues if building images from `Dockerfile` files from untrusted sources. Portainer and the Mesos executor will only have access to files readable to the user it's running as, so don't run the framework as `root`.*

#### 4. Launch Portainer

Now that you've got everything set up, you're  good to go. Because Portainer uses a pure-python implementation of the Mesos Framework API ([called pesos](http://github.com/wickman/pesos)), there is no requirement to install Apache Mesos itself to run the framework. You can use the invocation below as an example.

```
$ cd Portainer
$ ./bin/portainer \
        --mesos-master "localhost:5050" \
        --executor-uri "hdfs://my-namenode/path/to/portainer-executor.tar.gz" \
        build \
        --staging-uri "hdfs://my-namenode/tmp/portainer" \
        --tag "my_custom_tag" \
        --to "my-registry:5000" \
        example/Dockerfile
```
