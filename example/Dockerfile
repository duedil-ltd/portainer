#
# Example portainer Dockerfile template to build a docker image with the
# portainer source installed into /opt/portainer.
#

FROM ubuntu:12.04
MAINTAINER Tom Arnfeld <tom@duedil.com>

REPOSITORY tarnfeld/portainer
BUILD_CPU 0.1
BUILD_MEM 512

# Install dependencies
RUN apt-get update && apt-get install -y build-essential python-setuptools python-virtualenv

# Install the portainer source code
ADD ../ /opt/portainer

# Setup the python virtualenv
RUN cd /opt/portainer && bin/setup

WORKDIR /opt/portainer
# ENTRYPOINT bin/portainer
