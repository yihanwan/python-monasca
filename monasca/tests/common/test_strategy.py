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

import dateutil.parser as dparser
import time

from monasca.common import strategy
from monasca.openstack.common.fixture import config
from monasca.openstack.common import log
from monasca import tests

LOG = log.getLogger(__name__)


class TestStrategy(tests.BaseTestCase):

    def setUp(self):
        super(TestStrategy, self).setUp()
        self.CONF = self.useFixture(config.Config()).conf

    def test_hour(self):
        self.CONF.set_override('time_unit', 'h', group='strategy')
        self.strategy = strategy.IndexStrategy()

        day = dparser.parse('monkey 2014-07-10 love 12:34:56', fuzzy=True)
        self.assertEqual('20140710120000', self.strategy.get_index(day))

        # test input integer
        the_int = int(time.mktime(day.timetuple()))
        self.assertEqual('20140710120000', self.strategy.get_index(the_int))

        # test the str input
        self.assertEqual('20141115000000',
                         self.strategy.get_index('Nov 15, 2014 00:27:05'))

    def test_day(self):
        self.CONF.set_override('time_unit', 'd', group='strategy')
        self.strategy = strategy.IndexStrategy()

        day = dparser.parse('monkey 2014-07-10 love 12:34:56', fuzzy=True)
        self.assertEqual('20140710000000', self.strategy.get_index(day))
        day = dparser.parse('2014-07-10', fuzzy=True)
        self.assertEqual('20140710000000', self.strategy.get_index(day))

        # test input integer
        the_int = int(time.mktime(day.timetuple()))
        self.assertEqual('20140710000000', self.strategy.get_index(the_int))

        # test the str input
        self.assertEqual('20141115000000',
                         self.strategy.get_index('Nov 15, 2014'))

    def test_week(self):
        self.CONF.set_override('time_unit', 'w', group='strategy')
        self.strategy = strategy.IndexStrategy()

        day = dparser.parse('2013-10-31', fuzzy=True)
        self.assertEqual('20131027000000', self.strategy.get_index(day))
        day = dparser.parse('2013-11-1', fuzzy=True)
        self.assertEqual('20131027000000', self.strategy.get_index(day))
        day = dparser.parse('2013-11-3', fuzzy=True)
        self.assertEqual('20131103000000', self.strategy.get_index(day))
        day = dparser.parse('2014-09-12', fuzzy=True)
        self.assertEqual('20140907000000', self.strategy.get_index(day))
        day = dparser.parse('monkey 2014-07-10 love 12:34:56', fuzzy=True)
        self.assertEqual('20140706000000', self.strategy.get_index(day))

        # test input integer
        the_int = int(time.mktime(day.timetuple()))
        self.assertEqual('20140706000000', self.strategy.get_index(the_int))

        # test the str input
        self.assertEqual('20141109000000',
                         self.strategy.get_index('Nov 15, 2014'))

    def test_month(self):
        self.CONF.set_override('time_unit', 'm', group='strategy')
        self.strategy = strategy.IndexStrategy()

        day = dparser.parse('2014-10-31', fuzzy=True)
        self.assertEqual('20141001000000', self.strategy.get_index(day))
        day = dparser.parse('2014-11-1', fuzzy=True)
        self.assertEqual('20141101000000', self.strategy.get_index(day))
        day = dparser.parse('2014-11-15', fuzzy=True)
        self.assertEqual('20141101000000', self.strategy.get_index(day))

        # test input integer
        the_int = int(time.mktime(day.timetuple()))
        self.assertEqual('20141101000000', self.strategy.get_index(the_int))

        # test the str input
        self.assertEqual('20141101000000',
                         self.strategy.get_index('Nov 15, 2014'))

    def test_year(self):
        self.CONF.set_override('time_unit', 'y', group='strategy')
        self.strategy = strategy.IndexStrategy()

        day = dparser.parse('2014-10-31', fuzzy=True)
        self.assertEqual('20140101000000', self.strategy.get_index(day))
        day = dparser.parse('2014-11-1', fuzzy=True)
        self.assertEqual('20140101000000', self.strategy.get_index(day))
        day = dparser.parse('2014-11-15', fuzzy=True)
        self.assertEqual('20140101000000', self.strategy.get_index(day))

        # test input integer
        the_int = int(time.mktime(day.timetuple()))
        self.assertEqual('20140101000000', self.strategy.get_index(the_int))

        # test the str input
        self.assertEqual('20140101000000',
                         self.strategy.get_index('Nov 15, 2014'))
