#!/usr/bin/env python
#

from ez_setup import use_setuptools
use_setuptools()

from setuptools import setup

import os
import platform
import sys

GUI_SCRIPTS = []
VERSION = '0.1.5'


if platform.system() == 'Windows':
    GUI_SCRIPTS.append('lookup-gui = lookup:run_main')

    
setup(name='amazon-lookup',
      version=VERSION,
      description='Simple script to batch-lookup books by ISBN on amazon.',
      url='',
      download_url='',
      py_modules=['lookup',
                  'ez_setup',
                  ],
      entry_points = {
          'console_scripts': ['lookup = lookup:run_main'],
          'gui_scripts': GUI_SCRIPTS,
          },
      classifiers=[
        'Programming Language :: Python',
        ],
      install_requires=['google-apputils',
                        'python-gflags',
                        ],
      dependency_links = [],
      provides=[
        'lookup (%s)' % (VERSION,),
        ],
      )
