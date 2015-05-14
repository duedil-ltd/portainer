"""Minimal setup.py, not yet ready for publishing but just for pex packaging"""
from setuptools import setup, find_packages

# Fix to build sdist under vagrant, where hardlinks fail
# http://bugs.python.org/issue8876
import os
if 'vagrant' in str(os.environ):
    del os.link

setup(
    name='portainer',
    package_dir={
        'portainer': 'portainer'
    },
    packages=find_packages()
)
