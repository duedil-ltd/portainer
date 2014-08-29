#
# Example portainer Dockerfile template to build a docker image with the
# portainer source installed into /opt/portainer.
#

FROM ubuntu:12.04
MAINTAINER Tom Arnfeld <tom@duedil.com>

REPOSITORY portainer/test
BUILD_CPU 0.5
BUILD_MEM 256

WORKDIR /opt/portainer
ADD http://github.com/duedil-ltd/portainer/archive/master.zip /opt/portainer
