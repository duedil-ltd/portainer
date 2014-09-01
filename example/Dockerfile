#
# Example portainer Dockerfile template to build a docker image with the
# portainer source installed into /opt/portainer.
#

FROM ubuntu:12.04
MAINTAINER Tom Arnfeld <tom@duedil.com>

REPOSITORY portainer/example
BUILD_CPU 0.1
BUILD_MEM 512

ADD ../ /opt/portainer
WORKDIR /opt/portainer

ENTRYPOINT bin/portainer
