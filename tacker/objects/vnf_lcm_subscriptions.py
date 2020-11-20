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

from oslo_log import log as logging
from oslo_utils import timeutils
from sqlalchemy import func
from sqlalchemy import sql

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
def _vnf_lcm_subscriptions_get(context,
                               notification_type,
                               operation_type=None
                               ):

    subq = sql.select([models.VnfLcmFilters.subscription_uuid,
                       models.VnfLcmFilters.filter])
    if notification_type == 'VnfLcmOperationOccurrenceNotification':
        subq = subq.where(
            sql.and_(
                sql.or_(
                    models.VnfLcmFilters.notification_types_len == 0,
                    sql.func.json_contains(
                        models.VnfLcmFilters.notification_types,
                        f'"{_make_list(notification_type)}"')
                ),
                sql.or_(
                    models.VnfLcmFilters.operation_types_len == 0,
                    sql.func.json_contains(
                        models.VnfLcmFilters.operation_types,
                        f'"{_make_list(operation_type)}"')
                )
            ))
    else:
        subq = subq.where(
            sql.or_(
                models.VnfLcmFilters.notification_types_len == 0,
                func.json_contains(models.VnfLcmFilters.notification_types,
                                   f'"{_make_list(notification_type)}"')
            ))

    subq = subq.distinct().alias()
    q = sql.select([models.VnfLcmSubscriptions.id,
                    models.VnfLcmSubscriptions.callback_uri,
                    models.VnfLcmSubscriptions.subscription_authentication,
                    models.VnfLcmFilters.filter]).\
        where(sql.and_(
            models.VnfLcmSubscriptions.id == subq.subscription_uuid,
            models.VnfLcmSubscriptions.deleted == 0))

    return context.session.execute(q).all()


@db_api.context_manager.reader
def _vnf_lcm_subscriptions_show(context, subscriptionId):

    subq = sql.select([models.VnfLcmFilters.subscription_uuid,
                       models.VnfLcmFilters.filter]).\
        distinct().\
        alias()

    q = sql.select([models.VnfLcmSubscriptions.id,
                    models.VnfLcmSubscriptions.callback_uri,
                    models.VnfLcmFilters.filter]).\
        where(sql.and_(
            models.VnfLcmSubscriptions.id == subscriptionId,
            models.VnfLcmSubscriptions.id == subq.subscription_uuid,
            models.VnfLcmSubscriptions.deleted == 0))

    return context.session.execute(q).first()


@db_api.context_manager.reader
def _vnf_lcm_subscriptions_all(context):

    subq = sql.select([models.VnfLcmFilters.subscription_uuid,
                       models.VnfLcmFilters.filter]).\
        distinct().\
        alias()

    q = sql.select([models.VnfLcmSubscriptions.id,
                    models.VnfLcmSubscriptions.callback_uri,
                    models.VnfLcmFilters.filter]).\
        where(sql.and_(
            models.VnfLcmSubscriptions.id == subq.subscription_uuid,
            models.VnfLcmSubscriptions.deleted == 0))

    return context.session.execute(q).all()


@db_api.context_manager.reader
def _get_by_subscriptionid(context, subscriptionsId):

    query = api.model_query(context, models.VnfLcmSubscriptions,
                            read_deleted="no").\
        filter_by(id=subscriptionsId)

    return query.first()


@db_api.context_manager.reader
def _vnf_lcm_subscriptions_id_get(context,
                                  callbackUri,
                                  notification_type=None,
                                  operation_type=None
                                  ):

    subq = sql.select([models.VnfLcmFilters.subscription_uuid])
    if notification_type:
        subq = subq.where(
            sql.func.json_contains(
                models.VnfLcmFilters.notification_types,
                f'"{_make_list(notification_type)}"'))
    else:
        subq = subq.where(
            models.VnfLcmFilters.notification_types_len == 0)

    if operation_type:
        subq = subq.where(
            sql.func.json_contains(
                models.VnfLcmFilters.operation_types,
                f'"{_make_list(operation_type)}"'))
    else:
        subq = subq.where(
            models.VnfLcmFilters.operation_types_len == 0)

    subq = subq.alias()
    q = sql.select([models.VnfLcmSubscriptions.id]).\
        where(sql.and_(
            models.VnfLcmSubscriptions.id == subq.subscription_uuid,
            models.VnfLcmSubscriptions.callback_uri == callbackUri,
            models.VnfLcmSubscriptions.deleted == 0))

    return context.session.execute(q).all()


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

        callbackUri = values.callback_uri
        if filter:
            notification_type = filter.get('notificationTypes')
            operation_type = filter.get('operationTypes')

            vnf_lcm_subscriptions_id = _vnf_lcm_subscriptions_id_get(
                context,
                callbackUri,
                notification_type=notification_type,
                operation_type=operation_type)

            if vnf_lcm_subscriptions_id:
                raise Exception("303" + vnf_lcm_subscriptions_id)

            _add_filter_data(context, values.id, filter)

        else:
            vnf_lcm_subscriptions_id = _vnf_lcm_subscriptions_id_get(context,
                                            callbackUri)

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
                                  operation_type=None):
        return _vnf_lcm_subscriptions_get(context,
                                          notification_type,
                                          operation_type)

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
