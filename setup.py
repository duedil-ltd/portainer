#!/usr/bin/env python

from setuptools import setup


def read(filename):
    return open(filename).read()

setup(
    name="ddocker",
    version="0.0.1",
    description="Build docker images on a Mesos Cluster",
    long_description=read("README.md"),
    author="Tom Arnfeld",
    author_email="tom@duedil.com",
    maintainer="Tom Arnfeld",
    maintainer_email="tom@duedil.com",
    url="https://github.com/tarnfeld/ddocker",
    license=read("LICENSE"),
    packages=["ddocker"],
    scripts=["bin/ddocker"]
)
