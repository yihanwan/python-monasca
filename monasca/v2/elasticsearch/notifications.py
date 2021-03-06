# Copyright 2015 Carnegie Mellon University
#
# Author: Han Chen <hanc@andrew.cmu.edu>
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

import ast
import datetime
import falcon
from oslo.config import cfg
import requests
import re
import time
import uuid

from monasca.common import es_conn
from monasca.common import kafka_conn
from monasca.common import resource_api
from monasca.openstack.common import log
from monasca.openstack.common import timeutils as tu

try:
    import ujson as json
except ImportError:
    import json


opts = [
    cfg.StrOpt('topic', default='notification_methods',
               help='The topic that notification_methods will be published to.'),
    cfg.IntOpt('size', default=10000,
               help=('The query result limit. Any result set more than '
                     'the limit will be discarded. To see all the matching '
                     'result, narrow your search by using a small time '
                     'window or strong matching name')),
]

notification_group = cfg.OptGroup(name='notification', title='notification_methods')
cfg.CONF.register_group(notification_group)
cfg.CONF.register_opts(opts, notification_group)

LOG = log.getLogger(__name__)


class ParamUtil(object):

    @staticmethod
    def validateEmail(addr):
        if len(addr) > 7:
            if re.match("^.+\\@(\\[?)[a-zA-Z0-9\\-\\.]+\\.([a-zA-Z]{2,3}|[0-9]{1,3})(\\]?)$", addr) != None:
                return True
        return False

    @staticmethod
    def name(req):
        #parse name from request
        name = req.get_param('name')

        if name and name.strip():
            return name
        else:
            return "DefaultNotificationMethods"

    @staticmethod
    def type_address(req):
        #parse notification type from request
        #Default is EMAIL
        type = req.get_param('type')
        address = req.get_param('address')

        #Currently, notification method types of email, PagerDuty and webhooks are supported.
        # In the case of email, the address is the email address.
        # In the case of PagerDuty, the address is the PagerDuty Service API Key.
        # In the case of a webhook, the address is the URL of the webhook.
        if type and type.strip()== 'EMAIL'\
            and address and address.strip() \
            and ParamUtil.validateEmail(address.strip()):
            return ("EMAIL", address.strip())
        elif type and type.strip()== 'PAGEDUTY'\
            and address and address.strip():
            return ("PAGEDUTY", address.strip())
        elif type and type.strip()== 'WEBHOOK'\
            and address and address.strip():
            return ("WEBHOOK", address.strip())
        else:
            return None

class NotificationMethodDispatcher(object):
    def __init__(self, global_conf):
        LOG.debug('initializing V2API in NotificationMethodDispatcher!')
        super(NotificationMethodDispatcher, self).__init__()
        self.topic = cfg.CONF.notification.topic
        self.size = cfg.CONF.notification.size
        self._kafka_conn = kafka_conn.KafkaConnection(self.topic)
        self._es_conn = es_conn.ESConnection(self.topic)

    def post_data(self, req, res):
        LOG.debug('In NotificationMethodDispatcher::post_data.')
        msg = req.stream.read()
        # convert msg to dict
        dict_msg = ast.literal_eval(msg)

        # random uuid used for store the methods in database
        id = str(uuid.uuid4())

        # add an id to store in elasticsearch
        dict_msg["id"] = id

        # add an item "request" in the msg to tell the receiver this is a POST request
        # The final msg is something like:
        # {"id":"c60ec47e-5038-4bf1-9f95-4046c6e9a759",
        # "request":"POST",
        # "name":"TheName",
        # "type":"TheType",
        # "Address":"TheAddress"}
        dict_msg["request"] = "POST"

        LOG.debug("post notification method: %s" % dict_msg)
        code = self._kafka_conn.send_messages(json.dumps(dict_msg))
        res.status = getattr(falcon, 'HTTP_' + str(code))

    def put_data(self, req, res, id):
        LOG.debug('In NotificationMethodDispatcher::put_data.')
        msg = req.stream.read()

        dict_msg = ast.literal_eval(msg)

        # specify the id to match in elasticsearch for update
        dict_msg["id"] = id

        # add an item "request" in the msg to tell the receiver this is a PUT request
        dict_msg["request"] = "PUT"

        LOG.debug("delete notification method: %s" % dict_msg)
        code = self._kafka_conn.send_messages(json.dumps(dict_msg))
        res.status = getattr(falcon, 'HTTP_' + str(code))

    def del_data(self, req, res, id):
        LOG.debug('In NotificationMethodDispatcher::del_data.')

        dict_msg = {}

        # specify the id to match in elasticsearch for deletion
        dict_msg["id"] = id

        # add an item "request" in the msg to tell the receiver this is a DEL request
        dict_msg["request"] = "DEL"

        LOG.debug("delete notification method: %s" % dict_msg)
        code = self._kafka_conn.send_messages(json.dumps(dict_msg))
        res.status = getattr(falcon, 'HTTP_' + str(code))

    def _get_notification_method_response(self, res):
        if res and res.status_code == 200:
            obj = res.json()
            if obj:
                return obj.get('hits')
            return None
        else:
            return None

    @resource_api.Restify('/v2.0/notification-methods/{id}', method='get')
    def do_get_notification_methods(self, req, res, id):
        LOG.debug("The notification_methods GET request is received!")
        LOG.debug("---------------")
        LOG.debug(id)

        # Setup the get notification method query url, the url should be similar to this:
        # http://host:port/data_20141201/notification_methods/_search?size=10000?q=_id:35cc6f1c-3a29-49fb-a6fc-d9d97d190508
        # the url should be made of es_conn uri, the index prefix, notification
        # dispatcher topic, then add the key word _search.
        # self._query_url = ''.join([self._es_conn.uri,
        #                           self._es_conn.index_prefix, '/',
        #                           cfg.CONF.notification.topic,
        #                           '/_search?size=', str(self.size), '&q=_id:', id])
        #
        # LOG.debug(self._query_url)

        es_res = self._es_conn.get_message_by_id(id)
        res.status = getattr(falcon, 'HTTP_%s' % es_res.status_code)

        LOG.debug('Query to ElasticSearch returned: %s' % es_res.status_code)

        es_res = self._get_notification_method_response(es_res)
        LOG.debug('Query to ElasticSearch returned: %s' % es_res)

        res_data = es_res["hits"][0]
        if res_data:
            # convert the response into monasca notification_methods format
            res.body = json.dumps([{
            "id": id,
            "links": [{"rel": "self",
                       "href": req.uri}],
            "name":res_data["_source"]["name"],
            "type":res_data["_source"]["type"],
            "address":res_data["_source"]["address"]}])
            res.content_type = 'application/json;charset=utf-8'
        else:
            res.body = ''

    @resource_api.Restify('/v2.0/notification-methods/', method='post')
    def do_post_notification_methods(self, req, res):
        self.post_data(req, res)

    @resource_api.Restify('/v2.0/notification-methods/{id}', method='put')
    def do_put_notification_methods(self, req, res, id):
        self.put_data(req, res, id)

    @resource_api.Restify('/v2.0/notification-methods/{id}', method='delete')
    def do_delete_notification_methods(self, req, res, id):
        self.del_data(req, res, id)
