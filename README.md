
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
           ```````                               ,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,
````````````````````````````````                 \
                               |¸.·´¯`·.´¯`·.¸¸.·´\     o    o    o    o    o    o    o
                               |                   \
    __|___|___|___|___|___|    |                    \...................................
       |___|___|___|___|       |   (
         ___|___|___|___|      |    )  (      _/|_/       |  |
      |___|___|___|            |   (    )    <').-\        \/        Y
                               |    )  (     ``            |  /!-!\  |
                               |   (    )                   \|     |/
                               |    )  (                     _\___/_
                               |   (    )                   / /   \ \
```

Portainer is an [Apache Mesos](http://mesos.apache.org) framework that enables you to build docker images across a cluster of many machines. Given a valid `Dockerfile`, portainer can build your image and push it to a private registry faster than you can count to `n`.

When building docker images at scale, it can be time consuming and wasteful to manage dedicated infrastructure for building and pushing images. Building large containers with many sources and dependencies is a heavy operation, requiring large machines, and multiple of them. Deploying this infrastructure can be expensive and lead to poor utilization.

Given an existing Apache Mesos cluster, portainer can get to work right away. If you're new to Mesos, you can try out the Vagrant box provided, or learn more about the [Apache Mesos Architecture](http://mesos.apache.org/documentation/latest/mesos-architecture/) and [get started](http://mesos.apache.org/gettingstarted/).

**Note: If you are _not_ using the Mesos/Docker containerizer introduced in 0.20.0, this framework will currently not work for you. There isn't any reason it can't be supported, I've just not put the time into doing it. Contributions welcome! :)**


## Features

- Works out of the box with existing `Dockerfile` files
- Support for the new Docker containerizer in Mesos 0.20.0
- Configurable CPU/Memory resource limits for build tasks
- Full support for all `Dockerfile` commands, including local sources (e.g `ADD ./src`)
- Capable of building many many images in parallel across the cluster
- Introduces variables into the `Dockerfile` syntax for environment specific parameters

#### Not Supported

- Completely untested with the **public docker image index**


## Getting Started

### Framework Dependencies

You'll need to have the following dependencies installed to run the framework, though it's likely you'll only need to install the ones highlighted in bold;

- Python 2.7
- **Python `virtualenv`**
- **Protocol Buffers (`brew install protobuf`)**
- Make


## Building Images

#### 1. Upload the mesos executor

Before being able to use portainer, you need to upload the executor code for mesos to launch on the slave nodes. You can build it using `make executor`. If you have any changes locally, the script will exit and warn you before doing anything. The archive will be build into `./dist/` and needs to be uploaded somewhere mesos can reach it (HDFS, S3, FTP, HTTP etc).

Once you've uploaded that to somewhere.. save the full URL for later.

#### 2. Write your `Dockerfile`

As mentioned above, the `Dockerfile`s used by portainer are almost identical to those used by docker itself. There are a few extra commands that can be used as metadata for portainer, one of which is required. If you are keen to avoid hard coding these values into your Dockerfile's themselves, you can specify them at runtime with command line flags.

*Note: Adding these extra commands will **not** cause the `Dockerfile` to be unusable with the standard `docker build` command. They will simply be ignored.*

- `REGISTRY`    / `--registry` - The docker registry to push the image to once built
- `REPOSITORY`  / `--repository` - The name of the image repository (i.e `duedil-ltd/portainer` (**required**))
- `BUILD_CPU`   / `--build-cpu` - The number of CPUs required to build the image (a float)
- `BUILD_MEM`   / `--build-mem` - The amount of memory required to build the image (int, in megabytes)

For an example, take a look at the `Dockerfile` provided in the `./example` folder. This can be used to build an image of the portainer source code.

#### 3. Local `ADD` sources

If your `Dockerfile` (like the example provided) contains no `ADD` commands that use local files (`http://` is fine), you can skip this step entirely. If you do use local sources, continue reading.

Docker provides a way of bundling up local sources into the image being built, using the `ADD` command. For example;

```
ADD ./src /usr/lib/my-src
```

Since portainer will build your image on a remote machine, it has the ability to automatically discover these local sources, bundle them up, and upload them with the task. You can use any filesystem supported by [`pyfs`](github.com/duedil-ltd/pyfilesystem), including HDFS and S3. If you're using S3 you will need to configure the correct environment variables for authentication, being `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY`.

Use the `--staging-uri` command line flag to specify this. For example to distribute sources using your HDFS cluster, `--staging-uri=hdfs://my.namenode:50070/tmp/portainer`.

*Note: Portainer imposes no restrictions on symlinks or relative paths in `ADD` commands, unlike docker. In some situations this can pose security issues if building `Dockerfile`s from untrusted sources. Portainer and the mesos executor will only have access to files readable to the user it's running as, so don't run as `root`.*

#### 5. Variables

For re-usability, it can be valuable to replace certain values in your `Dockerfile` with runtime variables. An example being, if you have the same image pushed to multiple registries, hardcoding the `FROM` value to include a single private registry is an issue.

Currently one variable is provided built-in, `%REGISTRY%`. This will be populated with the private registry the image would be **pushed** to. Here's an example use case...

**foo/Dockerfile**

```
REPOSITORY test/foo
FROM ubuntu
RUN apt-get install htop
```

**bar/Dockerfile**

```
REPOSITORY test/bar
FROM %REGISTRY%/test/foo
RUN apt-get install something-else
```

With these two `Dockerfile` files, you can build the tree of images and push them to multiple registries easily, using the `--registry` command line flag.


#### 4. Launch portainer

Now that you've got everything set up, you should be good to go. Because portainer uses a pure-python implementation of the Mesos Framework API ([called pesos](http://github.com/wickman/pesos)) there is no requirement to install mesos itself.

```
$ cd portainer
$ ./bin/portainer example/Dockerfile.in \
        --mesos-master "localhost:5050" \
        --executor-uri "hdfs:///path/to/portainer-executor.tar.gz" \
        --tag "latest" \
        --tag "something_else"
```
