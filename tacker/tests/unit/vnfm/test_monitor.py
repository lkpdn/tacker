#
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
#

import json

import mock
from oslo_utils import timeutils
import testtools

from tacker.db.common_services import common_services_db_plugin
from tacker.plugins.common import constants
from tacker.vnfm import monitor

MOCK_VNF_ID = 'a737497c-761c-11e5-89c3-9cb6541d805d'
MOCK_VNF = {
    'id': MOCK_VNF_ID,
    'management_ip_addresses': {
        'vdu1': 'a.b.c.d'
    },
    'monitoring_policy': {
        'vdus': {
            'vdu1': {
                'ping': {
                    'actions': {
                        'failure': 'respawn'
                    },
                    'monitoring_params': {
                        'count': 1,
                        'monitoring_delay': 0,
                        'interval': 0,
                        'timeout': 2
                    }
                }
            }
        }
    },
    'boot_at': timeutils.utcnow(),
    'action_cb': mock.MagicMock()
}


MOCK_VNF_DEVICE_FOR_VDU_AUTOHEAL = {
    'id': MOCK_VNF_ID,
    'management_ip_addresses': {
        'vdu1': 'a.b.c.d'
    },
    'monitoring_policy': {
        'vdus': {
            'vdu1': {
                'ping': {
                    'actions': {
                        'failure': 'vdu_autoheal'
                    },
                    'monitoring_params': {
                        'count': 1,
                        'monitoring_delay': 0,
                        'interval': 0,
                        'timeout': 2
                    }
                }
            }
        }
    },
    'boot_at': timeutils.utcnow(),
    'action_cb': mock.MagicMock()
}


class TestVNFMonitor(testtools.TestCase):

    def setUp(self):
        super(TestVNFMonitor, self).setUp()
        p = mock.patch('tacker.common.driver_manager.DriverManager')
        self.mock_monitor_manager = p.start()
        mock.patch('tacker.db.common_services.common_services_db_plugin.'
                   'CommonServicesPluginDb.create_event'
                   ).start()
        self._cos_db_plugin =\
            common_services_db_plugin.CommonServicesPluginDb()
        self.addCleanup(p.stop)

    def test_to_hosting_vnf(self):
        test_vnf_dict = {
            'id': MOCK_VNF_ID,
            'mgmt_url': '{"vdu1": "a.b.c.d"}',
            'attributes': {
                'monitoring_policy': json.dumps(
                        MOCK_VNF['monitoring_policy'])
            }
        }
        action_cb = mock.MagicMock()
        expected_output = {
            'id': MOCK_VNF_ID,
            'action_cb': action_cb,
            'management_ip_addresses': {
                'vdu1': 'a.b.c.d'
            },
            'vnf': test_vnf_dict,
            'monitoring_policy': MOCK_VNF['monitoring_policy']
        }
        output_dict = monitor.VNFMonitor.to_hosting_vnf(test_vnf_dict,
                                                action_cb)
        self.assertEqual(expected_output, output_dict)

    @mock.patch('tacker.vnfm.monitor.VNFMonitor.__run__')
    def test_add_hosting_vnf(self, mock_monitor_run):
        test_vnf_dict = {
            'id': MOCK_VNF_ID,
            'mgmt_url': '{"vdu1": "a.b.c.d"}',
            'attributes': {
                'monitoring_policy': json.dumps(
                        MOCK_VNF['monitoring_policy'])
            },
            'status': 'ACTIVE'
        }
        action_cb = mock.MagicMock()
        test_boot_wait = 30
        test_vnfmonitor = monitor.VNFMonitor(test_boot_wait)
        new_dict = test_vnfmonitor.to_hosting_vnf(test_vnf_dict, action_cb)
        test_vnfmonitor.add_hosting_vnf(new_dict)
        test_vnf_id = list(test_vnfmonitor._hosting_vnfs.keys())[0]
        self.assertEqual(MOCK_VNF_ID, test_vnf_id)
        self._cos_db_plugin.create_event.assert_called_with(
            mock.ANY, res_id=mock.ANY, res_type=constants.RES_TYPE_VNF,
            res_state=mock.ANY, evt_type=constants.RES_EVT_MONITOR,
            tstamp=mock.ANY, details=mock.ANY)

    @mock.patch('tacker.vnfm.monitor.VNFMonitor.__run__')
    def test_run_monitor(self, mock_monitor_run):
        test_hosting_vnf = MOCK_VNF
        test_hosting_vnf['vnf'] = {'status': 'ACTIVE'}
        test_boot_wait = 30
        mock_kwargs = {
            'count': 1,
            'monitoring_delay': 0,
            'interval': 0,
            'mgmt_ip': 'a.b.c.d',
            'timeout': 2
        }
        test_vnfmonitor = monitor.VNFMonitor(test_boot_wait)
        self.mock_monitor_manager.invoke = mock.MagicMock()
        test_vnfmonitor._monitor_manager = self.mock_monitor_manager
        test_vnfmonitor.run_monitor(test_hosting_vnf)
        self.mock_monitor_manager \
            .invoke.assert_called_once_with('ping', 'monitor_call',
                                            vnf={'status': 'ACTIVE'},
                                            kwargs=mock_kwargs)

    @mock.patch('tacker.vnfm.monitor.VNFMonitor.__run__')
    @mock.patch('tacker.vnfm.monitor.VNFMonitor.monitor_call')
    def test_vdu_autoheal_action(self, mock_monitor_call, mock_monitor_run):
        test_hosting_vnf = MOCK_VNF_DEVICE_FOR_VDU_AUTOHEAL
        test_boot_wait = 30
        test_device_dict = {
            'status': 'ACTIVE',
            'id': MOCK_VNF_ID,
            'mgmt_url': '{"vdu1": "a.b.c.d"}',
            'attributes': {
                'monitoring_policy': json.dumps(
                    MOCK_VNF_DEVICE_FOR_VDU_AUTOHEAL['monitoring_policy'])
            }
        }
        test_hosting_vnf['vnf'] = test_device_dict
        mock_monitor_call.return_value = 'failure'
        test_vnfmonitor = monitor.VNFMonitor(test_boot_wait)
        test_vnfmonitor._monitor_manager = self.mock_monitor_manager
        test_vnfmonitor.run_monitor(test_hosting_vnf)
        test_hosting_vnf['action_cb'].assert_called_once_with(
            'vdu_autoheal', vdu_name='vdu1')

    @mock.patch('tacker.vnfm.monitor.VNFMonitor.__run__')
    def test_update_hosting_vnf(self, mock_monitor_run):
        test_boot_wait = 30
        test_vnfmonitor = monitor.VNFMonitor(test_boot_wait)
        vnf_dict = {
            'id': MOCK_VNF_ID,
            'mgmt_url': '{"vdu1": "a.b.c.d"}',
            'management_ip_addresses': 'a.b.c.d',
            'vnf': {
                'id': MOCK_VNF_ID,
                'mgmt_url': '{"vdu1": "a.b.c.d"}',
                'attributes': {
                    'monitoring_policy': json.dumps(
                        MOCK_VNF['monitoring_policy'])
                },
                'status': 'ACTIVE',
            }
        }

        test_vnfmonitor.add_hosting_vnf(vnf_dict)
        vnf_dict['status'] = 'PENDING_HEAL'
        test_vnfmonitor.update_hosting_vnf(vnf_dict)
        test_device_status = test_vnfmonitor._hosting_vnfs[MOCK_VNF_ID][
            'vnf']['status']
        self.assertEqual('PENDING_HEAL', test_device_status)
