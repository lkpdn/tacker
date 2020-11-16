#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import json

from oslo_log import log as logging
from oslo_utils import timeutils
from sqlalchemy.sql import text

from tacker.common import exceptions
import tacker.conf
from tacker.db import api as db_api
from tacker.db.db_sqlalchemy import api
from tacker.db.db_sqlalchemy import models
from tacker.objects import base
from tacker.objects import fields

_NO_DATA_SENTINEL = object()

LOG = logging.getLogger(__name__)
CONF = tacker.conf.CONF


def _make_list(value):
    if isinstance(value, list):
        res = ""
        for i in range(len(value)):
            t = "\"{}\"".format(value[i])
            if i == 0:
                res = str(t)
            else:
                res = "{0},{1}".format(res, t)

        res = "[{}]".format(res)
    else:
        res = "[\"{}\"]".format(str(value))
    return res


@db_api.context_manager.reader
def _vnf_lcm_subscriptions_show(context, subscriptionId):

    sql = text(
        "select "
        "t1.id,t1.callback_uri,t2.filter "
        "from vnf_lcm_subscriptions t1, "
        "(select distinct subscription_uuid,filter from vnf_lcm_filters) t2 "
        "where t1.id = t2.subscription_uuid "
        "and deleted = 0 "
        "and t1.id = :subsc_id")
    result_line = ""
    try:
        result = context.session.execute(sql, {'subsc_id': subscriptionId})
        for line in result:
            result_line = line
    except exceptions.NotFound:
        return ''
    except Exception as e:
        raise e
    return result_line


@db_api.context_manager.reader
def _vnf_lcm_subscriptions_all(context):

    sql = text(
        "select "
        "t1.id,t1.callback_uri,t2.filter "
        "from vnf_lcm_subscriptions t1, "
        "(select distinct subscription_uuid,filter from vnf_lcm_filters) t2 "
        "where t1.id = t2.subscription_uuid "
        "and deleted = 0 ")
    result_list = []
    try:
        result = context.session.execute(sql)
        for line in result:
            result_list.append(line)
    except Exception as e:
        raise e

    return result_list


@db_api.context_manager.reader
def _get_by_subscriptionid(context, subscriptionsId):

    sql = text("select id "
             "from vnf_lcm_subscriptions "
             "where id = :subsc_id "
             "and deleted = 0 ")
    try:
        result = context.session.execute(sql, {'subsc_id': subscriptionsId})
    except exceptions.NotFound:
        return ''
    except Exception as e:
        raise e

    return result


@db_api.context_manager.reader
def _vnf_lcm_subscriptions_no_instance_filtered(context,
                                                callback_uri=None,
                                                notification_types=None,
                                                operation_types=None,
                                                operation_states=None
                                                ):

    sql = ("select "
           "t1.id,t1.callback_uri,t1.subscription_authentication,t2.filter "
           "from vnf_lcm_subscriptions t1, "
           "(select subscription_uuid,filter from vnf_lcm_filters where ")

    if notification_types:
        sql = (sql + " JSON_CONTAINS(notification_types, '" +
               _make_list(notification_types) + "') and ")
    else:
        sql = sql + " notification_types_len=0 and "

    if notification_types == 'VnfLcmOperationOccurrenceNotification':
        if operation_types:
            sql = (sql + " JSON_CONTAINS(operation_types, '" +
                   _make_list(operation_types) + "') and ")
        else:
            sql = sql + " operation_types_len=0 and "
        if operation_states:
            sql = (sql + " JSON_CONTAINS(operation_states, '" +
                   _make_list(operation_states) + "') ")
        else:
            sql = sql + " operation_states_len=0 "

    sql = sql + ") t2 where t1.id=t2.subscription_uuid and t1.deleted=0"
    if callback_uri:
        sql = sql + " and t1.callback_uri= '" + callback_uri

    LOG.debug("sql[%s]" % sql)

    try:
        result = context.session.execute(sql)
        result_list = []
        for line in result:
            result_list.append(line)
        return result_list
    except exceptions.NotFound:
        return []


@db_api.context_manager.reader
def _vnf_lcm_subscriptions_yield(context,
                                 callback_uri=None,
                                 notification_types=None,
                                 operation_types=None,
                                 operation_states=None,
                                 vnfd_ids=None,
                                 vnf_products_from_providers=None,
                                 vnf_instance_ids=None,
                                 vnf_instance_names=None
                                 ):

    subscriptions = _vnf_lcm_subscriptions_no_instance_filtered(
        context, callback_uri, notification_types, operation_types,
        operation_states)

    for subscription in subscriptions:
        add = True
        lccn_filter = json.loads(subscription.get("filter", {}))
        ins_filter = lccn_filter.get("vnfInstanceSubscriptionFilter")

        # filter: $.vnfdIds
        vnfd_ids_filter = ins_filter.get("vnfdIds")
        if vnfd_ids_filter and (not vnfd_ids or
                not set(vnfd_ids).intersection(set(vnfd_ids_filter))):
            continue

        # filter: $.vnfProductsFromProviders
        provider_filters = ins_filter.get("vnfProductsFromProviders", [])
        if provider_filters and not vnf_products_from_providers:
            continue

        for provider_filter in provider_filters:
            add = False

            # filter: $.vnfProductsFromProviders[*].vnfProvider
            matched_products = [p.get("vnfProducts", [])
                    for p in vnf_products_from_providers
                    if provider_filter.get("vnfProvider") ==
                    p.get("vnfProvider")]
            if len(matched_products) == 0:
                continue

            add = True
            for product_filter in provider_filter.get("vnfProducts", []):
                add = False

                # filter: $.vnfProductsFromProviders[*].vnfProducts[*].
                #         vnfProductName
                matched_versions = [p.get("versions", [])
                        for p in matched_products
                        if p and product_filter.get("vnfProductName")
                        == p.get("vnfProductName")]
                if len(matched_versions) == 0:
                    continue

                add = True
                for version_filter in product_filter.get("versions", []):
                    add = False

                    # filter: $.vnfProductsFromProviders[*].vnfProducts[*].
                    #         versions[*].vnfSoftwareVersion
                    matched_vnfd_versions = [p.get("vnfdVersions", [])
                            for p in matched_versions
                            if p and version_filter.get("vnfSoftwareVersion")
                            == p.get("vnfSoftwareVersion")]
                    if len(matched_vnfd_versions) == 0:
                        continue

                    # filter: $.vnfProductsFromProviders[*].vnfProducts[*].
                    #         versions[*].vnfdVersions
                    vnfd_version_filters = version_filter.get(
                        "vnfdVersions", [])
                    if vnfd_version_filters and \
                            not set(sum(matched_vnfd_versions, [])).\
                            intersection(set(vnfd_version_filters)):
                        continue

                    add = True
                    break
                if add:
                    break
            if add:
                break
        if not add:
            continue

        # filter: $.vnfInstanceIds
        vnf_instance_ids_filter = ins_filter.get("vnfInstanceIds")
        if vnf_instance_ids_filter and (not vnf_instance_ids or
            not set(vnf_instance_ids).intersection(
                set(vnf_instance_ids_filter))):
            continue

        # filter: $.vnfInstanceNames
        vnf_instance_names_filter = ins_filter.get("vnfInstanceNames")
        if vnf_instance_names_filter and (not vnf_instance_names or
            not set(vnf_instance_names).intersection(
                set(vnf_instance_names_filter))):
            continue

        yield subscription


@db_api.context_manager.reader
def _vnf_lcm_subscriptions_get(context,
                               notification_types,
                               operation_types=None,
                               operation_states=None,
                               vnfd_ids=None,
                               vnf_products_from_providers=None,
                               vnf_instance_ids=None,
                               vnf_instance_names=None,
                               ):
    return [subscription for subscription in
        _vnf_lcm_subscriptions_yield(
            context,
            notification_types=notification_types,
            operation_types=operation_types,
            operation_states=operation_states,
            vnfd_ids=vnfd_ids,
            vnf_products_from_providers=vnf_products_from_providers,
            vnf_instance_ids=vnf_instance_ids,
            vnf_instance_names=vnf_instance_names,
        )]


@db_api.context_manager.reader
def _vnf_lcm_subscriptions_id_get(context,
                                  callback_uri,
                                  notification_types=None,
                                  operation_types=None,
                                  operation_states=None,
                                  vnfd_ids=None,
                                  vnf_products_from_providers=None,
                                  vnf_instance_ids=None,
                                  vnf_instance_names=None,
                                  ):
    for subscription in \
            _vnf_lcm_subscriptions_yield(
                context,
                callback_uri=callback_uri,
                notification_types=notification_types,
                operation_types=operation_types,
                operation_states=operation_states,
                vnfd_ids=vnfd_ids,
                vnf_products_from_providers=vnf_products_from_providers,
                vnf_instance_ids=vnf_instance_ids,
                vnf_instance_names=vnf_instance_names,
            ):
        return subscription.get("id")


def _add_filter_data(context, subscription_id, filter):
    with db_api.context_manager.writer.using(context):

        new_entries = []
        new_entries.append({"subscription_uuid": subscription_id,
                            "filter": filter})

        context.session.execute(
            models.VnfLcmFilters.__table__.insert(None),
            new_entries)


@db_api.context_manager.writer
def _vnf_lcm_subscriptions_create(context, values, filter):
    with db_api.context_manager.writer.using(context):

        new_entries = []
        if 'subscription_authentication' in values:
            new_entries.append({"id": values.id,
                                "callback_uri": values.callback_uri,
                                "subscription_authentication":
                                    values.subscription_authentication})
        else:
            new_entries.append({"id": values.id,
                                "callback_uri": values.callback_uri})

        context.session.execute(
            models.VnfLcmSubscriptions.__table__.insert(None),
            new_entries)

        callback_uri = values.callback_uri
        if filter:
            notification_types = filter.get('notificationTypes')
            operation_types = filter.get('operationTypes')
            operation_states = filter.get('operationStates')

            vis_filter = filter.get('vnfInstanceSubscriptionFilter', {})
            vnfd_ids = vis_filter.get('vnfdIds')
            vnf_products_from_providers = vis_filter.get(
                'vnfProductsFromProviders')
            vnf_instance_ids = vis_filter.get('vnfInstanceIds')
            vnf_instance_names = vis_filter.get('vnfInstanceNames')

            vnf_lcm_subscriptions_id = _vnf_lcm_subscriptions_id_get(
                context,
                callback_uri,
                notification_types=notification_types,
                operation_types=operation_types,
                operation_states=operation_states,
                vnfd_ids=vnfd_ids,
                vnf_products_from_providers=vnf_products_from_providers,
                vnf_instance_ids=vnf_instance_ids,
                vnf_instance_names=vnf_instance_names)

            if vnf_lcm_subscriptions_id:
                raise Exception("303" + vnf_lcm_subscriptions_id)

            _add_filter_data(context, values.id, filter)

        else:
            vnf_lcm_subscriptions_id = _vnf_lcm_subscriptions_id_get(context,
                                            callback_uri)

            if vnf_lcm_subscriptions_id:
                raise Exception("303" + vnf_lcm_subscriptions_id.id)
            _add_filter_data(context, values.id, {})

    return values


@db_api.context_manager.writer
def _destroy_vnf_lcm_subscription(context, subscriptionId):
    now = timeutils.utcnow()
    updated_values = {'deleted': 1,
                      'deleted_at': now}
    try:
        api.model_query(context, models.VnfLcmSubscriptions). \
            filter_by(id=subscriptionId). \
            update(updated_values, synchronize_session=False)
    except Exception as e:
        raise e


@base.TackerObjectRegistry.register
class LccnSubscriptionRequest(base.TackerObject, base.TackerPersistentObject):

    # Version 1.0: Initial version
    VERSION = '1.0'

    fields = {
        'id': fields.UUIDField(nullable=False),
        'callback_uri': fields.StringField(nullable=False),
        'subscription_authentication':
            fields.DictOfStringsField(nullable=True),
        'filter': fields.StringField(nullable=True)
    }

    @base.remotable
    def create(self, filter):
        updates = self.obj_clone()
        db_vnf_lcm_subscriptions = _vnf_lcm_subscriptions_create(
            self._context, updates, filter)

        LOG.debug(
            'test_log: db_vnf_lcm_subscriptions %s' %
            db_vnf_lcm_subscriptions)

        return db_vnf_lcm_subscriptions

    @base.remotable_classmethod
    def vnf_lcm_subscriptions_show(cls, context, subscriptionId):
        try:
            vnf_lcm_subscriptions = _vnf_lcm_subscriptions_show(
                context, subscriptionId)
        except Exception as e:
            raise e
        return vnf_lcm_subscriptions

    @base.remotable_classmethod
    def vnf_lcm_subscriptions_list(cls, context):
        # get vnf_lcm_subscriptions data
        try:
            vnf_lcm_subscriptions = _vnf_lcm_subscriptions_all(context)
        except Exception as e:
            raise e

        return vnf_lcm_subscriptions

    @base.remotable_classmethod
    def vnf_lcm_subscriptions_get(cls, context,
                                  notification_type,
                                  operation_type=None,
                                  operation_state=None,
                                  vnf_instances=[]):

        vnfd_ids = []
        vnf_instance_ids = []
        vnf_instance_names = []
        vnf_products_from_providers = []
        for vnf_instance in vnf_instances:
            vnf_instance_dict = vnf_instance.to_dict()
            vnfd_ids.append(vnf_instance_dict.get('vnfd_id'))
            vnf_instance_ids.append(
                vnf_instance_dict.get('vnf_instance_id'))
            vnf_instance_names.append(
                vnf_instance_dict.get('vnf_instance_name'))
            vnf_products_from_providers.append({
                'vnfProvider': vnf_instance_dict.get('vnf_provider'),
                'vnfProducts': {
                    'vnfProductName': vnf_instance_dict.get(
                        'vnf_product_name'),
                    'versions': {
                        'vnfSoftwareVersion': vnf_instance_dict.get(
                            'vnf_software_version'),
                        'vnfdVersions': vnf_instance_dict.get('vnfd_version')
                    }
                }
            })

        return _vnf_lcm_subscriptions_get(
            context,
            notification_type=notification_type,
            operation_types=operation_type,
            operation_states=operation_state,
            vnfd_ids=vnfd_ids,
            vnf_products_from_providers=vnf_products_from_providers,
            vnf_instance_ids=vnf_instance_ids,
            vnf_instance_names=vnf_instance_names)

    @base.remotable_classmethod
    def destroy(cls, context, subscriptionId):
        try:
            get_subscriptionid = _get_by_subscriptionid(
                context, subscriptionId)
        except Exception as e:
            raise e

        if not get_subscriptionid:
            return 404

        try:
            _destroy_vnf_lcm_subscription(context, subscriptionId)
        except Exception as e:
            raise e

        return 204
