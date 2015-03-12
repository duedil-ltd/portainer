"""Minimal setup.py, not yet ready for publishing but just for pex packaging"""
from setuptools import setup

setup(
    name='portainer',
    package_dir={
        'portainer': 'portainer'
    },
    packages=[
        'portainer'
    ]
)
