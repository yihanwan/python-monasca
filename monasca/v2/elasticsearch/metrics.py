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

import datetime
import falcon
from oslo.config import cfg
import requests
import time

from monasca.common import es_conn
from monasca.common import kafka_conn
from monasca.common import resource_api
from monasca.openstack.common import log
from monasca.openstack.common import timeutils as tu

try:
    import ujson as json
except ImportError:
    import json


metrics_opts = [
    cfg.StrOpt('topic', default='metrics',
               help='The topic that metrics will be published to.'),
    cfg.IntOpt('size', default=10000,
               help=('The query result limit. Any result set more than '
                     'the limit will be discarded. To see all the matching '
                     'result, narrow your search by using a small time '
                     'window or strong matching name')),
]

metrics_group = cfg.OptGroup(name='metrics', title='metrics')
cfg.CONF.register_group(metrics_group)
cfg.CONF.register_opts(metrics_opts, metrics_group)

LOG = log.getLogger(__name__)


class ParamUtil(object):

    @staticmethod
    def _default_st():
        # default start time will be 30 days ago
        return tu.utcnow() - datetime.timedelta(30)

    @staticmethod
    def _default_et():
        # default end time will be current time
        return tu.utcnow()

    @staticmethod
    def common(req, q):
        # process metric name
        name = req.get_param('name')
        if name and name.strip():
            q.append({'match': {'name': name.strip()}})

        # handle start and end time
        try:
            st = req.get_param('start_time')
            st = tu.parse_isotime(st) if st else ParamUtil._default_st()
            st = st.timetuple()
            et = req.get_param('end_time')
            et = tu.parse_isotime(et) if et else ParamUtil._default_et()
            et = et.timetuple()
            q.append({'range': {'timestamp': {'lt': time.mktime(et),
                                              'gte': time.mktime(st)}}})
        except Exception:
            return False

        # handle dimensions
        dimensions = req.get_param('dimensions')
        matches = []

        def _handle_pair(pair):
            param = pair.split(':')
            if len(param) == 2 and param[0] and param[1]:
                key = param[0].strip()
                value = param[1].strip()
                # in case that the value is numeric
                try:
                    value = float(param[1].strip())
                except Exception:
                    # The value is not numeric, so use as is.
                    pass
                matches.append({'match': {'dimensions.' + key: value}})

        if dimensions:
            map(_handle_pair, dimensions.split(','))
            q += matches

        return True

    @staticmethod
    def period(req):
        try:
            if req.get_param('period'):
                return str(int(req.get_param('period'))) + 's'
        except Exception:
            pass
        return '300s'

    @staticmethod
    def stats(req):
        try:
            s = req.get_param('statistics')
            if s:
                return [x.strip() for x in s.lower().split(',')]
        except Exception:
            pass
        return ['avg', 'count', 'max', 'min', 'sum']


class MetricDispatcher(object):
    def __init__(self, global_conf):
        LOG.debug('initializing V2API!')
        super(MetricDispatcher, self).__init__()
        self.topic = cfg.CONF.metrics.topic
        self.size = cfg.CONF.metrics.size
        self._kafka_conn = kafka_conn.KafkaConnection(self.topic)
        self._es_conn = es_conn.ESConnection(self.topic)

        # Setup the get metrics query body pattern
        self._query_body = {
            "query": {"bool": {"must": []}},
            "size": self.size}

        self._aggs_body = {}
        self._stats_body = {}
        self._sort_clause = []

        # Setup the get metrics query url, the url should be similar to this:
        # http://host:port/data_20141201/metrics/_search
        # the url should be made of es_conn uri, the index prefix, metrics
        # dispatcher topic, then add the key word _search.
        self._query_url = ''.join([self._es_conn.uri,
                                  self._es_conn.index_prefix, '*/',
                                  cfg.CONF.metrics.topic,
                                  '/_search?search_type=count'])

        # the url to get all the properties of metrics
        self._query_mapping_url = ''.join([self._es_conn.uri,
                                           self._es_conn.index_prefix,
                                           '*/_mappings/',
                                           cfg.CONF.metrics.topic])

        # Setup metrics query aggregation command. To see the structure of
        # the aggregation, copy and paste it to a json formatter.
        self._metrics_agg = """
        {"by_name":{"terms":{"field":"name","size":%(size)d},
        "aggs":{"by_dim":{"terms":{"field":"dimensions_hash","size":%(size)d},
        "aggs":{"metrics":{"top_hits":{"_source":{"exclude":
        ["dimensions_hash","timestamp","value"]},"size":1}}}}}}}
        """

        self._measure_agg = """
        {"by_name":{"terms":{"field":"name","size":%(size)d},
        "aggs":{"by_dim":{"terms":{"field":"dimensions_hash",
        "size": %(size)d},"aggs":{"dimension":{"top_hits":{
        "_source":{"exclude":["dimensions_hash","timestamp",
        "value"]},"size":1}},"measures": {"top_hits":{
        "_source": {"include": ["timestamp", "value"]},
        "sort": [{"timestamp": "asc"}],"size": %(size)d}}}}}}}
        """

        self._stats_agg = """
        {"by_name":{"terms":{"field":"name","size":%(size)d},
        "aggs":{"by_dim":{"terms":{"field":"dimensions_hash",
        "size":%(size)d},"aggs":{"dimension":{"top_hits":{"_source":
        {"exclude":["dimensions_hash","timestamp","value"]},"size":1}},
        "periods":{"date_histogram":{"field":"timestamp",
        "interval":"%(period)s"},"aggs":{"statistics":{"stats":
        {"field":"value"}}}}}}}}}
        """

    def post_data(self, req, res):
        LOG.debug('Getting the call.')
        msg = req.stream.read()

        code = self._kafka_conn.send_messages(msg)
        res.status = getattr(falcon, 'HTTP_' + str(code))

    def _get_agg_response(self, res):
        if res and res.status_code == 200:
            obj = res.json()
            if obj:
                return obj.get('aggregations')
            return None
        else:
            return None

    @resource_api.Restify('/v2.0/metrics/', method='get')
    def do_get_metrics(self, req, res):
        LOG.debug('The metrics GET request is received!')

        # process query conditions
        query = []
        ParamUtil.common(req, query)
        _metrics_ag = self._metrics_agg % {"size": self.size}
        if query:
            body = ('{"query":{"bool":{"must":' + json.dumps(query) + '}},'
                    '"size":' + str(self.size) + ','
                    '"aggs":' + _metrics_ag + '}')
        else:
            body = '{"aggs":' + _metrics_ag + '}'

        LOG.debug('Request body:' + body)
        es_res = requests.post(self._query_url, data=body)
        res.status = getattr(falcon, 'HTTP_%s' % es_res.status_code)

        LOG.debug('Query to ElasticSearch returned: %s' % es_res.status_code)
        res_data = self._get_agg_response(es_res)
        if res_data:
            # convert the response into monasca metrics format
            aggs = res_data['by_name']['buckets']
            flag = {'is_first': True}

            def _render_hits(item):
                rslt = item['metrics']['hits']['hits'][0]['_source']
                if flag['is_first']:
                    flag['is_first'] = False
                    return json.dumps(rslt)
                else:
                    return ',' + json.dumps(rslt)

            def _make_body(buckets):
                yield '['
                for by_name in buckets:
                    if by_name['by_dim']:
                        for by_dim in by_name['by_dim']['buckets']:
                            yield _render_hits(by_dim)
                yield ']'

            res.body = ''.join(_make_body(aggs))
            res.content_type = 'application/json;charset=utf-8'
        else:
            res.body = ''

    @resource_api.Restify('/v2.0/metrics/', method='post')
    def do_post_metrics(self, req, res):
        self.post_data(req, res)

    @resource_api.Restify('/v2.0/metrics/measurements', method='get')
    def do_get_measurements(self, req, res):
        LOG.debug('The metrics measurements GET request is received!')
        # process query conditions
        query = []
        ParamUtil.common(req, query)
        _measure_ag = self._measure_agg % {"size": self.size}
        if query:
            body = ('{"query":{"bool":{"must":' + json.dumps(query) + '}},'
                    '"size":' + str(self.size) + ','
                    '"aggs":' + _measure_ag + '}')
        else:
            body = '{"aggs":' + _measure_ag + '}'

        LOG.debug('Request body:' + body)
        es_res = requests.post(self._query_url, data=body)
        res.status = getattr(falcon, 'HTTP_%s' % es_res.status_code)

        LOG.debug('Query to ElasticSearch returned: %s' % es_res.status_code)
        res_data = self._get_agg_response(es_res)
        if res_data:
            # convert the response into monasca metrics format
            metrics = res_data['by_name']['buckets']

            def _render_metric(dim):
                source = dim['dimension']['hits']['hits'][0]['_source']
                yield '{"name":"' + source['name'] + '","dimensions":'
                yield json.dumps(source['dimensions'])
                yield ',"columns":["id","timestamp","value"],"measurements":['
                is_first = True
                for measure in dim['measures']['hits']['hits']:
                    ss = measure['_source']
                    m = ('["' + measure['_id'] + '","' +
                         tu.iso8601_from_timestamp(ss['timestamp']) +
                         '",' + str(ss['value']) + ']')
                    if is_first:
                        yield m
                        is_first = False
                    else:
                        yield ',' + m
                yield ']}'

            def _make_body(items):
                is_first = True
                yield '['
                for metric in items:
                    for dim in metric['by_dim']['buckets']:
                        if is_first:
                            is_first = False
                        else:
                            yield ','
                        for result in _render_metric(dim):
                            yield result
                yield ']'

            res.body = ''.join(_make_body(metrics))
            res.content_type = 'application/json;charset=utf-8'
        else:
            res.body = ''

    @resource_api.Restify('/v2.0/metrics/statistics', method='get')
    def do_get_statistics(self, req, res):
        # process query conditions
        query = []
        ParamUtil.common(req, query)
        period = ParamUtil.period(req)
        stats = ParamUtil.stats(req)

        _stats_ag = self._stats_agg % {"size": self.size, "period": period}
        if query:
            body = ('{"query":{"bool":{"must":' + json.dumps(query) + '}},'
                    '"size":' + str(self.size) + ','
                    '"aggs":' + _stats_ag + '}')
        else:
            body = '{"aggs":' + _stats_ag + '}'

        es_res = requests.post(self._query_url, data=body)
        res.status = getattr(falcon, 'HTTP_%s' % es_res.status_code)

        LOG.debug('Query to ElasticSearch returned: %s' % es_res.status_code)
        res_data = self._get_agg_response(es_res)
        if res_data:
            # convert the response into monasca metrics format
            aggs = res_data['by_name']['buckets']

            col_fields = ['timestamp'] + stats
            col_json = json.dumps(col_fields)

            def _render_stats(dim):
                source = dim['dimension']['hits']['hits'][0]['_source']
                yield '{"name":"' + source['name'] + '","dimensions":'
                yield json.dumps(source['dimensions'])
                yield ',"columns":' + col_json + ',"statistics":['
                is_first = True
                for item in dim['periods']['buckets']:
                    m = ('["' + tu.iso8601_from_timestamp(item['key']) +
                         '"')
                    for s in stats:
                        m += ',' + str(item['statistics'][s])
                    m += ']'
                    if is_first:
                        yield m
                        is_first = False
                    else:
                        yield ',' + m
                yield ']}'

            def _make_body(items):
                is_first = True
                yield '['
                for metric in items:
                    for dim in metric['by_dim']['buckets']:
                        if is_first:
                            is_first = False
                        else:
                            yield ','
                        for result in _render_stats(dim):
                            yield result
                yield ']'

            res.body = ''.join(_make_body(aggs))
            res.content_type = 'application/json;charset=utf-8'
        else:
            res.body = ''
