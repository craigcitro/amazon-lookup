#!/usr/bin/env python
#

from ez_setup import use_setuptools
use_setuptools()

from setuptools import setup

import os
import platform
import sys


setup(name='amazon-lookup',
      version='0.1',
      description='Simple script to batch-lookup books by ISBN on amazon.',
      url='',
      download_url='',
      py_modules=['lookup',
                  ],
      entry_points = {
          'console_scripts': ['lookup = lookup:run_main']
          },
      classifiers=[
        'Programming Language :: Python',
        ],
      install_requires=['google-apputils',
                        'python-gflags',
                        ],
      dependency_links = [],
      provides=[
        'lookup (0.1)',
        ],
      )
