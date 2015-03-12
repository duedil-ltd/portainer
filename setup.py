"""Minimal setup.py, not yet ready for publishing but just for pex packaging"""
from setuptools import setup, find_packages

setup(
    name='portainer',
    package_dir={
        'portainer': 'portainer'
    },
    packages=find_packages()
)
