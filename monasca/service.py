#!/usr/bin/env python
#
# Copyright 2013 IBM Corp
#
# Author: Tong Li <litong01@us.ibm.com>
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import sys

from oslo.config import cfg

from monasca.openstack.common import gettextutils
from monasca.openstack.common import log


cfg.CONF.import_opt('default_log_levels', 'monasca.openstack.common.log')

LOG = log.getLogger(__name__)


def prepare_service(argv=None):
    gettextutils.install('monasca')
    gettextutils.enable_lazy()
    log_levels = (cfg.CONF.default_log_levels)
    cfg.set_defaults(log.log_opts, default_log_levels=log_levels)
    if argv is None:
        argv = sys.argv
    cfg.CONF(argv[1:], project='monasca')
    log.setup('monasca')
    LOG.info('Service has started!')
