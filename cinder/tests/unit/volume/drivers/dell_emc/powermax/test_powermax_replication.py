# Copyright (c) 2017-2019 Dell Inc. or its subsidiaries.
# All Rights Reserved.
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

import ast
from copy import deepcopy

import mock
import six

from cinder import exception
from cinder.objects import fields
from cinder import test
from cinder.tests.unit.volume.drivers.dell_emc.powermax import (
    powermax_data as tpd)
from cinder.tests.unit.volume.drivers.dell_emc.powermax import (
    powermax_fake_objects as tpfo)
from cinder.volume.drivers.dell_emc.powermax import common
from cinder.volume.drivers.dell_emc.powermax import fc
from cinder.volume.drivers.dell_emc.powermax import iscsi
from cinder.volume.drivers.dell_emc.powermax import masking
from cinder.volume.drivers.dell_emc.powermax import provision
from cinder.volume.drivers.dell_emc.powermax import rest
from cinder.volume.drivers.dell_emc.powermax import utils
from cinder.volume import volume_utils


class PowerMaxReplicationTest(test.TestCase):
    def setUp(self):
        self.data = tpd.PowerMaxData()
        super(PowerMaxReplicationTest, self).setUp()
        self.replication_device = self.data.sync_rep_device
        volume_utils.get_max_over_subscription_ratio = mock.Mock()
        configuration = tpfo.FakeConfiguration(
            None, 'CommonReplicationTests', interval=1, retries=1,
            san_ip='1.1.1.1', san_login='smc', vmax_array=self.data.array,
            vmax_srp='SRP_1', san_password='smc', san_api_port=8443,
            vmax_port_groups=[self.data.port_group_name_f],
            replication_device=self.replication_device)
        rest.PowerMaxRest._establish_rest_session = mock.Mock(
            return_value=tpfo.FakeRequestsSession())
        driver = fc.PowerMaxFCDriver(configuration=configuration)
        iscsi_config = tpfo.FakeConfiguration(
            None, 'CommonReplicationTests', interval=1, retries=1,
            san_ip='1.1.1.1', san_login='smc', vmax_array=self.data.array,
            vmax_srp='SRP_1', san_password='smc', san_api_port=8443,
            vmax_port_groups=[self.data.port_group_name_i],
            replication_device=self.replication_device)
        iscsi_driver = iscsi.PowerMaxISCSIDriver(configuration=iscsi_config)
        self.iscsi_common = iscsi_driver.common
        self.driver = driver
        self.common = self.driver.common
        self.masking = self.common.masking
        self.provision = self.common.provision
        self.rest = self.common.rest
        self.utils = self.common.utils
        self.utils.get_volumetype_extra_specs = (
            mock.Mock(
                return_value=self.data.vol_type_extra_specs_rep_enabled))
        self.extra_specs = deepcopy(self.data.extra_specs_rep_enabled)
        self.extra_specs['retries'] = 1
        self.extra_specs['interval'] = 1
        self.extra_specs['rep_mode'] = 'Synchronous'
        self.async_rep_device = self.data.async_rep_device
        async_configuration = tpfo.FakeConfiguration(
            None, 'CommonReplicationTests', interval=1, retries=1,
            san_ip='1.1.1.1', san_login='smc', vmax_array=self.data.array,
            vmax_srp='SRP_1', san_password='smc', san_api_port=8443,
            vmax_port_groups=[self.data.port_group_name_f],
            replication_device=self.async_rep_device)
        self.async_driver = fc.PowerMaxFCDriver(
            configuration=async_configuration)
        self.metro_rep_device = self.data.metro_rep_device
        metro_configuration = tpfo.FakeConfiguration(
            None, 'CommonReplicationTests', interval=1, retries=1,
            san_ip='1.1.1.1', san_login='smc', vmax_array=self.data.array,
            vmax_srp='SRP_1', san_password='smc', san_api_port=8443,
            vmax_port_groups=[self.data.port_group_name_f],
            replication_device=self.metro_rep_device)
        self.metro_driver = fc.PowerMaxFCDriver(
            configuration=metro_configuration)

    def test_get_replication_info(self):
        self.common._get_replication_info()
        self.assertTrue(self.common.replication_enabled)

    @mock.patch.object(common.PowerMaxCommon, '_remove_members')
    @mock.patch.object(
        common.PowerMaxCommon, '_get_replication_extra_specs',
        return_value=tpd.PowerMaxData.rep_extra_specs2)
    @mock.patch.object(
        utils.PowerMaxUtils, 'is_volume_failed_over', return_value=True)
    def test_unmap_lun_volume_failed_over(self, mock_fo, mock_es, mock_rm):
        extra_specs = deepcopy(self.extra_specs)
        extra_specs[utils.PORTGROUPNAME] = self.data.port_group_name_f
        extra_specs[utils.IS_RE] = True
        extra_specs[utils.FORCE_VOL_REMOVE] = True
        rep_config = self.data.rep_config_sync
        rep_config[utils.RDF_CONS_EXEMPT] = False
        extra_specs[utils.REP_CONFIG] = rep_config
        self.common._unmap_lun(self.data.test_volume, self.data.connector)
        mock_es.assert_called_once_with(extra_specs, rep_config)

    @mock.patch.object(common.PowerMaxCommon, '_remove_members')
    @mock.patch.object(
        common.PowerMaxCommon, '_get_replication_extra_specs',
        return_value=tpd.PowerMaxData.rep_extra_specs)
    @mock.patch.object(
        utils.PowerMaxUtils, 'is_metro_device', return_value=True)
    def test_unmap_lun_metro(self, mock_md, mock_es, mock_rm):
        extra_specs = deepcopy(self.extra_specs)
        extra_specs[utils.PORTGROUPNAME] = self.data.port_group_name_f
        self.common._unmap_lun(self.data.test_volume, self.data.connector)
        self.assertEqual(2, mock_rm.call_count)

    @mock.patch.object(
        utils.PowerMaxUtils, 'is_volume_failed_over', return_value=True)
    def test_initialize_connection_vol_failed_over(self, mock_fo):
        extra_specs = deepcopy(self.extra_specs)
        extra_specs[utils.PORTGROUPNAME] = self.data.port_group_name_f

        rep_extra_specs = deepcopy(tpd.PowerMaxData.rep_extra_specs)
        rep_extra_specs[utils.PORTGROUPNAME] = self.data.port_group_name_f

        rep_config = self.data.rep_config_sync
        extra_specs[utils.REP_CONFIG] = rep_config
        rep_config[utils.RDF_CONS_EXEMPT] = False

        with mock.patch.object(self.common, '_get_replication_extra_specs',
                               return_value=rep_extra_specs) as mock_es:
            self.common.initialize_connection(
                self.data.test_volume, self.data.connector)
            mock_es.assert_called_once_with(extra_specs, rep_config)

    @mock.patch.object(utils.PowerMaxUtils, 'is_metro_device',
                       return_value=True)
    @mock.patch.object(rest.PowerMaxRest, 'get_array_model_info',
                       return_value=('VMAX250F', False))
    def test_initialize_connection_vol_metro(self, mock_model, mock_md):
        metro_connector = deepcopy(self.data.connector)
        metro_connector['multipath'] = True
        info_dict = self.common.initialize_connection(
            self.data.test_volume, metro_connector)
        ref_dict = {'array': self.data.array,
                    'device_id': self.data.device_id,
                    'hostlunid': 3,
                    'maskingview': self.data.masking_view_name_f,
                    'metro_hostlunid': 3}
        self.assertEqual(ref_dict, info_dict)

    @mock.patch.object(rest.PowerMaxRest, 'get_iscsi_ip_address_and_iqn',
                       return_value=([tpd.PowerMaxData.ip],
                                     tpd.PowerMaxData.initiator))
    @mock.patch.object(common.PowerMaxCommon, '_get_replication_extra_specs',
                       return_value=tpd.PowerMaxData.rep_extra_specs)
    @mock.patch.object(utils.PowerMaxUtils, 'is_metro_device',
                       return_value=True)
    def test_initialize_connection_vol_metro_iscsi(self, mock_md, mock_es,
                                                   mock_ip):
        metro_connector = deepcopy(self.data.connector)
        metro_connector['multipath'] = True
        info_dict = self.iscsi_common.initialize_connection(
            self.data.test_volume, metro_connector)
        ref_dict = {'array': self.data.array,
                    'device_id': self.data.device_id,
                    'hostlunid': 3,
                    'maskingview': self.data.masking_view_name_f,
                    'ip_and_iqn': [{'ip': self.data.ip,
                                    'iqn': self.data.initiator}],
                    'metro_hostlunid': 3,
                    'is_multipath': True,
                    'metro_ip_and_iqn': [{'ip': self.data.ip,
                                          'iqn': self.data.initiator}]}
        self.assertEqual(ref_dict, info_dict)

    @mock.patch.object(utils.PowerMaxUtils, 'is_metro_device',
                       return_value=True)
    def test_initialize_connection_no_multipath_iscsi(self, mock_md):
        info_dict = self.iscsi_common.initialize_connection(
            self.data.test_volume, self.data.connector)
        self.assertIsNone(info_dict)

    @mock.patch.object(
        masking.PowerMaxMasking, 'pre_multiattach',
        return_value=tpd.PowerMaxData.masking_view_dict_multiattach)
    def test_attach_metro_volume(self, mock_pre):
        rep_extra_specs = deepcopy(tpd.PowerMaxData.rep_extra_specs)
        rep_extra_specs[utils.PORTGROUPNAME] = self.data.port_group_name_f
        hostlunid, remote_port_group = self.common._attach_metro_volume(
            self.data.test_volume, self.data.connector, False,
            self.data.extra_specs, rep_extra_specs)
        self.assertEqual(self.data.port_group_name_f, remote_port_group)
        # Multiattach case
        self.common._attach_metro_volume(
            self.data.test_volume, self.data.connector, True,
            self.data.extra_specs, rep_extra_specs)
        mock_pre.assert_called_once()

    def test_set_config_file_get_extra_specs_rep_enabled(self):
        extra_specs, _ = self.common._set_config_file_and_get_extra_specs(
            self.data.test_volume)
        self.assertTrue(extra_specs['replication_enabled'])

    def test_populate_masking_dict_is_re(self):
        extra_specs = deepcopy(self.extra_specs)
        extra_specs[utils.PORTGROUPNAME] = self.data.port_group_name_f
        masking_dict = self.common._populate_masking_dict(
            self.data.test_volume, self.data.connector, extra_specs)
        self.assertTrue(masking_dict['replication_enabled'])
        self.assertEqual('OS-HostX-SRP_1-DiamondDSS-OS-fibre-PG-RE',
                         masking_dict[utils.SG_NAME])

    @mock.patch.object(common.PowerMaxCommon,
                       '_remove_vol_and_cleanup_replication')
    @mock.patch.object(masking.PowerMaxMasking,
                       'remove_vol_from_storage_group')
    @mock.patch.object(common.PowerMaxCommon, '_delete_from_srp')
    @mock.patch.object(common.PowerMaxCommon, '_sync_check')
    def test_cleanup_replication_source(
            self, mck_sync, mock_del, mock_rm, mock_clean):
        self.common._cleanup_replication_source(
            self.data.array, self.data.test_volume, 'vol1',
            {'device_id': self.data.device_id}, self.extra_specs)
        mock_del.assert_called_once_with(
            self.data.array, self.data.device_id, 'vol1', self.extra_specs)

    def test_get_rdf_details(self):
        rdf_group_no, remote_array = self.common.get_rdf_details(
            self.data.array, self.data.rep_config_sync)
        self.assertEqual(self.data.rdf_group_no_1, rdf_group_no)
        self.assertEqual(self.data.remote_array, remote_array)

    def test_get_rdf_details_exception(self):
        with mock.patch.object(self.rest, 'get_rdf_group_number',
                               return_value=None):
            self.assertRaises(exception.VolumeBackendAPIException,
                              self.common.get_rdf_details, self.data.array,
                              self.data.rep_config_sync)

    @mock.patch.object(common.PowerMaxCommon, '_sync_check')
    def test_failover_host(self, mck_sync):
        volumes = [self.data.test_volume, self.data.test_clone_volume]
        with mock.patch.object(self.common, '_failover_replication',
                               return_value=(None, {})) as mock_fo:
            self.common.failover_host(volumes)
            mock_fo.assert_called_once()

    @mock.patch.object(common.PowerMaxCommon, 'failover_replication',
                       return_value=({}, {}))
    def test_failover_host_groups(self, mock_fg):
        volumes = [self.data.test_volume_group_member]
        group1 = self.data.test_group
        self.common.failover_host(volumes, None, [group1])
        mock_fg.assert_called_once()

    @mock.patch.object(rest.PowerMaxRest,
                       'get_array_model_info',
                       return_value=('VMAX250F', False))
    def test_get_replication_extra_specs(self, mock_model):
        rep_config = self.data.rep_config_sync
        # Path one - disable compression
        extra_specs1 = deepcopy(self.extra_specs)
        extra_specs1[utils.DISABLECOMPRESSION] = 'true'
        ref_specs1 = deepcopy(self.data.rep_extra_specs5)
        ref_specs1['rdf_group_label'] = self.data.rdf_group_name_1
        ref_specs1['rdf_group_no'] = self.data.rdf_group_no_1
        rep_extra_specs1 = self.common._get_replication_extra_specs(
            extra_specs1, rep_config)
        self.assertEqual(ref_specs1, rep_extra_specs1)
        # Path two - disable compression, not all flash
        ref_specs2 = deepcopy(self.data.rep_extra_specs5)
        ref_specs2['rdf_group_label'] = self.data.rdf_group_name_1
        ref_specs2['rdf_group_no'] = self.data.rdf_group_no_1
        with mock.patch.object(self.rest, 'is_compression_capable',
                               return_value=False):
            rep_extra_specs2 = self.common._get_replication_extra_specs(
                extra_specs1, rep_config)
        self.assertEqual(ref_specs2, rep_extra_specs2)

    @mock.patch.object(rest.PowerMaxRest,
                       'get_array_model_info',
                       return_value=('PowerMax 2000', True))
    def test_get_replication_extra_specs_powermax(self, mock_model):
        rep_config = self.data.rep_config_sync
        rep_specs = deepcopy(self.data.rep_extra_specs5)
        extra_specs = deepcopy(self.extra_specs)

        # SLO not valid, both SLO and Workload set to NONE
        rep_specs['slo'] = None
        rep_specs['workload'] = None
        rep_specs['target_array_model'] = 'PowerMax 2000'
        rep_specs['rdf_group_label'] = self.data.rdf_group_name_1
        rep_specs['rdf_group_no'] = self.data.rdf_group_no_1

        with mock.patch.object(self.provision, 'verify_slo_workload',
                               return_value=(False, False)):
            rep_extra_specs = self.common._get_replication_extra_specs(
                extra_specs, rep_config)
            self.assertEqual(rep_specs, rep_extra_specs)
        # SL valid, workload invalid, only workload set to NONE
        rep_specs['slo'] = 'Diamond'
        rep_specs['workload'] = None
        rep_specs['target_array_model'] = 'PowerMax 2000'
        with mock.patch.object(self.provision, 'verify_slo_workload',
                               return_value=(True, False)):
            rep_extra_specs = self.common._get_replication_extra_specs(
                extra_specs, rep_config)
            self.assertEqual(rep_specs, rep_extra_specs)

    def test_get_secondary_stats(self):
        rep_config = self.data.rep_config_sync
        array_map = self.common.get_attributes_from_cinder_config()
        finalarrayinfolist = self.common._get_slo_workload_combinations(
            array_map)
        array_info = finalarrayinfolist[0]
        ref_info = deepcopy(array_info)
        ref_info['SerialNumber'] = six.text_type(rep_config['array'])
        ref_info['srpName'] = rep_config['srp']
        secondary_info = self.common.get_secondary_stats_info(
            rep_config, array_info)
        self.assertEqual(ref_info, secondary_info)

    @mock.patch.object(common.PowerMaxCommon, 'get_volume_metadata',
                       return_value=tpd.PowerMaxData.volume_metadata)
    def test_replicate_group(self, mck_meta):
        volume_model_update = {
            'id': self.data.test_volume.id,
            'provider_location': self.data.test_volume.provider_location}
        extra_specs = deepcopy(self.data.extra_specs_rep_enabled)
        extra_specs[utils.REP_CONFIG] = self.data.rep_config_sync
        vols_model_update = self.common._replicate_group(
            self.data.array, [volume_model_update],
            self.data.test_vol_grp_name, extra_specs)
        ref_rep_data = {'array': self.data.remote_array,
                        'device_id': self.data.device_id2}
        ref_vol_update = {
            'id': self.data.test_volume.id,
            'provider_location': self.data.test_volume.provider_location,
            'replication_driver_data': ref_rep_data,
            'replication_status': fields.ReplicationStatus.ENABLED,
            'metadata': self.data.volume_metadata}

        # Decode string representations of dicts into dicts, because
        # the string representations are randomly ordered and therefore
        # hard to compare.
        vols_model_update[0]['replication_driver_data'] = ast.literal_eval(
            vols_model_update[0]['replication_driver_data'])

        self.assertEqual(ref_vol_update, vols_model_update[0])

    @mock.patch.object(
        utils.PowerMaxUtils, 'validate_non_replication_group_config')
    @mock.patch.object(volume_utils, 'is_group_a_cg_snapshot_type',
                       return_value=True)
    @mock.patch.object(volume_utils, 'is_group_a_type', return_value=False)
    def test_create_group(self, mock_type, mock_cg_type, mck_validate):
        ref_model_update = {
            'status': fields.GroupStatus.AVAILABLE}
        model_update = self.common.create_group(None, self.data.test_group_1)
        self.assertEqual(ref_model_update, model_update)
        extra_specs_list = [self.data.vol_type_extra_specs_rep_enabled]
        mck_validate.assert_called_once_with(extra_specs_list)

    @mock.patch.object(
        utils.PowerMaxUtils, 'validate_replication_group_config')
    @mock.patch.object(volume_utils, 'is_group_a_cg_snapshot_type',
                       return_value=False)
    @mock.patch.object(volume_utils, 'is_group_a_type', return_value=True)
    def test_create_replicaton_group(
            self, mock_type, mock_cg_type, mck_validate):
        ref_model_update = {
            'status': fields.GroupStatus.AVAILABLE,
            'replication_status': fields.ReplicationStatus.ENABLED}
        model_update = self.common.create_group(None, self.data.test_group_1)
        self.assertEqual(ref_model_update, model_update)
        extra_specs_list = [self.data.vol_type_extra_specs_rep_enabled]
        mck_validate.assert_called_once_with(
            self.common.rep_configs, extra_specs_list)

    def test_enable_replication(self):
        # Case 1: Group not replicated
        with mock.patch.object(volume_utils, 'is_group_a_type',
                               return_value=False):
            self.assertRaises(NotImplementedError,
                              self.common.enable_replication,
                              None, self.data.test_group,
                              [self.data.test_volume])
        with mock.patch.object(volume_utils, 'is_group_a_type',
                               return_value=True):
            # Case 2: Empty group
            model_update, __ = self.common.enable_replication(
                None, self.data.test_group, [])
            self.assertEqual({}, model_update)
            # Case 3: Successfully enabled
            model_update, __ = self.common.enable_replication(
                None, self.data.test_group, [self.data.test_volume])
            self.assertEqual(fields.ReplicationStatus.ENABLED,
                             model_update['replication_status'])
            # Case 4: Exception
            model_update, __ = self.common.enable_replication(
                None, self.data.test_group_failed, [self.data.test_volume])
            self.assertEqual(fields.ReplicationStatus.ERROR,
                             model_update['replication_status'])

    def test_disable_replication(self):
        # Case 1: Group not replicated
        with mock.patch.object(volume_utils, 'is_group_a_type',
                               return_value=False):
            self.assertRaises(NotImplementedError,
                              self.common.disable_replication,
                              None, self.data.test_group,
                              [self.data.test_volume])
        with mock.patch.object(volume_utils, 'is_group_a_type',
                               return_value=True):
            # Case 2: Empty group
            model_update, __ = self.common.disable_replication(
                None, self.data.test_group, [])
            self.assertEqual({}, model_update)
            # Case 3: Successfully disabled
            model_update, __ = self.common.disable_replication(
                None, self.data.test_group, [self.data.test_volume])
            self.assertEqual(fields.ReplicationStatus.DISABLED,
                             model_update['replication_status'])
            # Case 4: Exception
            model_update, __ = self.common.disable_replication(
                None, self.data.test_group_failed, [self.data.test_volume])
            self.assertEqual(fields.ReplicationStatus.ERROR,
                             model_update['replication_status'])

    def test_failover_replication_empty_group(self):
        with mock.patch.object(volume_utils, 'is_group_a_type',
                               return_value=True):
            model_update, __ = self.common.failover_replication(
                None, self.data.test_group, [])
            self.assertEqual({}, model_update)

    @mock.patch.object(rest.PowerMaxRest, 'srdf_failover_group',
                       return_value=tpd.PowerMaxData.rdf_group_no_1)
    @mock.patch.object(common.PowerMaxCommon, 'get_rdf_details',
                       return_value=tpd.PowerMaxData.rdf_group_no_1)
    @mock.patch.object(common.PowerMaxCommon, '_find_volume_group',
                       return_value=tpd.PowerMaxData.test_group)
    def test_failover_replication_failover(self, mck_find_vol_grp,
                                           mck_get_rdf_grp, mck_failover):
        volumes = [self.data.test_volume_group_member]
        vol_group = self.data.test_group
        vol_grp_name = self.data.test_group.name

        model_update, __ = self.common._failover_replication(
            volumes, vol_group, vol_grp_name, host=True)
        self.assertEqual(fields.ReplicationStatus.FAILED_OVER,
                         model_update['replication_status'])

    @mock.patch.object(rest.PowerMaxRest, 'srdf_failover_group',
                       return_value=tpd.PowerMaxData.rdf_group_no_1)
    @mock.patch.object(common.PowerMaxCommon, 'get_rdf_details',
                       return_value=tpd.PowerMaxData.rdf_group_no_1)
    @mock.patch.object(common.PowerMaxCommon, '_find_volume_group',
                       return_value=tpd.PowerMaxData.test_group)
    def test_failover_replication_failback(self, mck_find_vol_grp,
                                           mck_get_rdf_grp, mck_failover):
        volumes = [self.data.test_volume_group_member]
        vol_group = self.data.test_group
        vol_grp_name = self.data.test_group.name

        model_update, __ = self.common._failover_replication(
            volumes, vol_group, vol_grp_name, host=True,
            secondary_backend_id='default')
        self.assertEqual(fields.ReplicationStatus.ENABLED,
                         model_update['replication_status'])

    @mock.patch.object(common.PowerMaxCommon, 'get_rdf_details',
                       return_value=None)
    @mock.patch.object(common.PowerMaxCommon, '_find_volume_group',
                       return_value=tpd.PowerMaxData.test_group)
    def test_failover_replication_exception(self, mck_find_vol_grp,
                                            mck_get_rdf_grp):
        volumes = [self.data.test_volume_group_member]
        vol_group = self.data.test_group
        vol_grp_name = self.data.test_group.name

        model_update, __ = self.common._failover_replication(
            volumes, vol_group, vol_grp_name)
        self.assertEqual(fields.ReplicationStatus.ERROR,
                         model_update['replication_status'])

    @mock.patch.object(utils.PowerMaxUtils, 'get_volumetype_extra_specs',
                       return_value={utils.REPLICATION_DEVICE_BACKEND_ID:
                                     tpd.PowerMaxData.rep_backend_id_sync})
    @mock.patch.object(utils.PowerMaxUtils, 'get_volume_group_utils',
                       return_value=(tpd.PowerMaxData.array, {}))
    @mock.patch.object(common.PowerMaxCommon, '_cleanup_group_replication')
    @mock.patch.object(volume_utils, 'is_group_a_type', return_value=True)
    def test_delete_replication_group(self, mock_check,
                                      mock_cleanup, mock_utils, mock_get):
        group = self.data.test_rep_group
        group['volume_types'] = self.data.test_volume_type_list
        self.common._delete_group(group, [])
        mock_cleanup.assert_called_once()

    @mock.patch.object(masking.PowerMaxMasking,
                       'remove_volumes_from_storage_group')
    @mock.patch.object(utils.PowerMaxUtils, 'check_rep_status_enabled')
    @mock.patch.object(common.PowerMaxCommon,
                       '_remove_remote_vols_from_volume_group')
    @mock.patch.object(masking.PowerMaxMasking,
                       'add_remote_vols_to_volume_group')
    @mock.patch.object(volume_utils, 'is_group_a_type', return_value=True)
    @mock.patch.object(volume_utils, 'is_group_a_cg_snapshot_type',
                       return_value=True)
    def test_update_replicated_group(self, mock_cg_type, mock_type_check,
                                     mock_add, mock_remove, mock_check,
                                     mock_rm):
        add_vols = [self.data.test_volume]
        remove_vols = [self.data.test_clone_volume]
        self.common.update_group(
            self.data.test_group_1, add_vols, remove_vols)
        mock_add.assert_called_once()
        mock_remove.assert_called_once()

    @mock.patch.object(masking.PowerMaxMasking,
                       'remove_volumes_from_storage_group')
    def test_remove_remote_vols_from_volume_group(self, mock_rm):
        self.common._remove_remote_vols_from_volume_group(
            self.data.remote_array, [self.data.test_volume],
            self.data.test_rep_group, self.data.rep_extra_specs)
        mock_rm.assert_called_once()

    @mock.patch.object(masking.PowerMaxMasking, 'remove_and_reset_members')
    @mock.patch.object(masking.PowerMaxMasking,
                       'remove_volumes_from_storage_group')
    def test_cleanup_group_replication(self, mock_rm, mock_rm_reset):
        self.common._cleanup_group_replication(
            self.data.array, self.data.test_vol_grp_name,
            [self.data.device_id], self.extra_specs, self.data.rep_config_sync)
        mock_rm.assert_called_once()

    @mock.patch.object(common.PowerMaxCommon, '_failover_replication',
                       return_value=({}, {}))
    @mock.patch.object(common.PowerMaxCommon, '_sync_check')
    def test_failover_host_async(self, mck_sync, mock_fg):
        volumes = [self.data.test_volume]
        extra_specs = deepcopy(self.extra_specs)
        extra_specs['rep_mode'] = utils.REP_ASYNC
        with mock.patch.object(common.PowerMaxCommon, '_initial_setup',
                               return_value=extra_specs):
            self.async_driver.common.failover_host(volumes, None, [])
        mock_fg.assert_called_once()

    @mock.patch.object(
        common.PowerMaxCommon, 'get_volume_metadata', return_value={})
    @mock.patch.object(
        rest.PowerMaxRest, 'srdf_resume_replication')
    @mock.patch.object(
        common.PowerMaxCommon, '_protect_storage_group',
        return_value=(fields.ReplicationStatus.ENABLED,
                      tpd.PowerMaxData.replication_update,
                      tpd.PowerMaxData.rep_info_dict))
    @mock.patch.object(
        masking.PowerMaxMasking, 'add_volume_to_default_storage_group')
    @mock.patch.object(
        common.PowerMaxCommon, 'configure_volume_replication',
        return_value=(
            'first_vol_in_rdf_group', tpd.PowerMaxData.replication_update,
            tpd.PowerMaxData.rep_info_dict,
            tpd.PowerMaxData.rep_extra_specs_mgmt, True))
    @mock.patch.object(
        rest.PowerMaxRest, 'rename_volume')
    @mock.patch.object(
        common.PowerMaxCommon, '_check_lun_valid_for_cinder_management',
        return_value=(tpd.PowerMaxData.test_volume.name,
                      tpd.PowerMaxData.storagegroup_name_source))
    @mock.patch.object(
        utils.PowerMaxUtils, 'get_array_and_device_id',
        return_value=(tpd.PowerMaxData.array, tpd.PowerMaxData.device_id))
    @mock.patch.object(
        common.PowerMaxCommon, '_initial_setup',
        return_value=tpd.PowerMaxData.rep_extra_specs)
    def test_manage_existing_enable_replication(
            self, mck_setup, mck_get_array, mck_check_lun, mck_rename,
            mck_configure, mck_add, mck_post, mck_resume, mck_meta):

        external_ref = {u'source-name': u'00002'}
        volume = self.data.test_volume
        ref_model_update = {
            'metadata': {'BackendID': 'None'},
            'provider_location': six.text_type({
                'device_id': self.data.device_id,
                'array': self.data.array}),
            'replication_driver_data': six.text_type({
                'device_id': self.data.device_id2,
                'array': self.data.remote_array}),
            'replication_status': fields.ReplicationStatus.ENABLED}

        model_update = self.common.manage_existing(volume, external_ref)
        mck_configure.assert_called_once()
        mck_add.assert_called_once()
        mck_post.assert_called_once()
        mck_resume.assert_called_once()
        self.assertEqual(ref_model_update, model_update)

    @mock.patch.object(
        masking.PowerMaxMasking, 'add_volume_to_default_storage_group',
        side_effect=exception.VolumeBackendAPIException)
    @mock.patch.object(
        common.PowerMaxCommon, 'configure_volume_replication',
        return_value=(
            'first_vol_in_rdf_group', tpd.PowerMaxData.replication_update,
            tpd.PowerMaxData.rep_info_dict,
            tpd.PowerMaxData.rep_extra_specs, True))
    @mock.patch.object(
        rest.PowerMaxRest, 'rename_volume')
    @mock.patch.object(
        common.PowerMaxCommon, '_check_lun_valid_for_cinder_management',
        return_value=(tpd.PowerMaxData.test_volume.name,
                      tpd.PowerMaxData.storagegroup_name_source))
    @mock.patch.object(
        utils.PowerMaxUtils, 'get_array_and_device_id',
        return_value=(tpd.PowerMaxData.array, tpd.PowerMaxData.device_id))
    @mock.patch.object(
        common.PowerMaxCommon, '_initial_setup',
        return_value=tpd.PowerMaxData.rep_extra_specs)
    def test_manage_existing_enable_replication_exception(
            self, mck_setup, mck_get_array, mck_check_lun, mck_rename,
            mck_configure, mck_add):
        external_ref = {u'source-name': u'00002'}
        volume = self.data.test_volume
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.common.manage_existing, volume, external_ref)
        self.assertEqual(2, mck_rename.call_count)

    @mock.patch.object(
        common.PowerMaxCommon, 'get_volume_metadata',
        return_value={'device-meta-key-1': 'device-meta-value-1',
                      'device-meta-key-2': 'device-meta-value-2'})
    @mock.patch.object(
        common.PowerMaxCommon, '_create_volume',
        return_value=(
            tpd.PowerMaxData.provider_location,
            {'replication_driver_data': tpd.PowerMaxData.provider_location2},
            {}))
    @mock.patch.object(
        common.PowerMaxCommon, '_initial_setup',
        return_value=tpd.PowerMaxData.rep_extra_specs_rep_config)
    def test_create_rep_volume(self, mck_initial, mck_create, mck_meta):
        ref_model_update = (
            {'provider_location': six.text_type(self.data.provider_location),
             'replication_driver_data': (
                 tpd.PowerMaxData.provider_location2),
             'metadata': {'BackendID': self.data.rep_backend_id_sync,
                          'device-meta-key-1': 'device-meta-value-1',
                          'device-meta-key-2': 'device-meta-value-2',
                          'user-meta-key-1': 'user-meta-value-1',
                          'user-meta-key-2': 'user-meta-value-2'}})
        volume = deepcopy(self.data.test_volume)
        volume.metadata = {'user-meta-key-1': 'user-meta-value-1',
                           'user-meta-key-2': 'user-meta-value-2'}
        model_update = self.common.create_volume(volume)
        self.assertEqual(ref_model_update, model_update)

    @mock.patch.object(common.PowerMaxCommon, 'get_volume_metadata',
                       return_value={})
    @mock.patch.object(
        common.PowerMaxCommon, '_create_cloned_volume',
        return_value=(
            tpd.PowerMaxData.provider_location,
            tpd.PowerMaxData.replication_update, {}))
    def test_create_rep_volume_from_snapshot(self, mck_meta, mck_clone_chk):
        ref_model_update = (
            {'provider_location': six.text_type(self.data.provider_location),
             'metadata': {'BackendID': self.data.rep_backend_id_sync}})
        ref_model_update.update(self.data.replication_update)
        model_update = self.common.create_volume_from_snapshot(
            self.data.test_clone_volume, self.data.test_snapshot)
        self.assertEqual(ref_model_update, model_update)

    @mock.patch.object(
        common.PowerMaxCommon, 'get_volume_metadata',
        return_value=tpd.PowerMaxData.volume_metadata)
    @mock.patch.object(
        common.PowerMaxCommon, '_create_cloned_volume',
        return_value=(
            tpd.PowerMaxData.provider_location_clone,
            tpd.PowerMaxData.replication_update, {}))
    @mock.patch.object(common.PowerMaxCommon, '_clone_check')
    def test_cloned_rep_volume(self, mck_clone, mck_meta, mck_clone_chk):
        metadata = deepcopy(self.data.volume_metadata)
        metadata['BackendID'] = self.data.rep_backend_id_sync
        ref_model_update = {
            'provider_location': six.text_type(
                self.data.provider_location_clone),
            'metadata': metadata}
        ref_model_update.update(self.data.replication_update)
        model_update = self.common.create_cloned_volume(
            self.data.test_clone_volume, self.data.test_volume)
        self.assertEqual(ref_model_update, model_update)

    @mock.patch.object(common.PowerMaxCommon, '_validate_rdfg_status')
    @mock.patch.object(
        common.PowerMaxCommon, '_add_volume_to_rdf_management_group')
    @mock.patch.object(
        common.PowerMaxCommon, 'get_and_set_remote_device_uuid',
        return_value=tpd.PowerMaxData.device_id2)
    @mock.patch.object(common.PowerMaxCommon, 'srdf_protect_storage_group')
    @mock.patch.object(
        provision.PowerMaxProvision, 'create_volume_from_sg',
        return_value=tpd.PowerMaxData.provider_location)
    @mock.patch.object(
        masking.PowerMaxMasking, 'get_or_create_default_storage_group',
        return_value=tpd.PowerMaxData.default_sg_re_enabled)
    @mock.patch.object(
        common.PowerMaxCommon, 'prepare_replication_details',
        return_value=(True, tpd.PowerMaxData.rep_extra_specs_rep_config,
                      {}, True))
    @mock.patch.object(
        provision.PowerMaxProvision, 'verify_slo_workload',
        return_value=(True, True))
    def test_create_volume_rep_enabled(
            self, mck_slo, mck_prep, mck_get, mck_create, mck_protect, mck_set,
            mck_add, mck_valid):
        volume = self.data.test_volume
        volume_name = self.data.volume_id
        volume_size = 1
        extra_specs = deepcopy(self.data.rep_extra_specs)
        extra_specs['mode'] = utils.REP_ASYNC
        extra_specs[utils.REP_CONFIG] = self.data.rep_config_async
        volume_dict, rep_update, rep_info_dict = self.common._create_volume(
            volume, volume_name, volume_size, extra_specs)
        self.assertEqual(self.data.provider_location, volume_dict)
        self.assertEqual(self.data.replication_update, rep_update)
        self.assertIsNone(rep_info_dict)

    @mock.patch.object(common.PowerMaxCommon, 'get_rdf_details',
                       return_value=(tpd.PowerMaxData.rdf_group_no_1, None))
    @mock.patch.object(utils.PowerMaxUtils, 'is_replication_enabled',
                       side_effect=[False, True])
    def test_remove_vol_and_cleanup_replication(self, mck_rep, mck_get):
        array = self.data.array
        rdf_group_no = self.data.rdf_group_no_1
        device_id = self.data.device_id
        volume = self.data.test_volume
        volume_name = self.data.test_volume.name
        extra_specs = deepcopy(self.data.extra_specs)
        extra_specs[utils.REP_CONFIG] = self.data.rep_config_sync

        with mock.patch.object(
                self.masking, 'remove_and_reset_members') as mock_rm:
            self.common._remove_vol_and_cleanup_replication(
                array, device_id, volume_name, extra_specs, volume)
            mock_rm.assert_called_once_with(
                array, volume, device_id, volume_name, extra_specs, False)
        with mock.patch.object(
                self.common, 'cleanup_rdf_device_pair') as mock_clean:
            self.common._remove_vol_and_cleanup_replication(
                array, device_id, volume_name, extra_specs, volume)
            mock_clean.assert_called_once_with(
                array, rdf_group_no, device_id, extra_specs)

    @mock.patch.object(utils.PowerMaxUtils, 'is_replication_enabled',
                       return_value=False)
    def test_remove_vol_and_cleanup_replication_host_assisted_migration(
            self, mck_rep):
        array = self.data.array
        device_id = self.data.device_id
        volume = deepcopy(self.data.test_volume)
        volume.migration_status = 'deleting'
        metadata = deepcopy(self.data.volume_metadata)
        metadata[utils.IS_RE_CAMEL] = 'False'
        volume.metadata = metadata
        volume_name = self.data.test_volume.name
        extra_specs = deepcopy(self.data.rep_extra_specs)
        extra_specs[utils.REP_CONFIG] = self.data.rep_config_sync
        ref_extra_specs = deepcopy(extra_specs)
        ref_extra_specs.pop(utils.IS_RE)

        with mock.patch.object(
                self.masking, 'remove_and_reset_members') as mock_rm:
            self.common._remove_vol_and_cleanup_replication(
                array, device_id, volume_name, extra_specs, volume)
            mock_rm.assert_called_once_with(
                array, volume, device_id, volume_name, ref_extra_specs, False)

    @mock.patch.object(common.PowerMaxCommon, '_validate_rdfg_status')
    @mock.patch.object(
        common.PowerMaxCommon, 'get_volume_metadata', return_value='')
    @mock.patch.object(rest.PowerMaxRest, 'srdf_resume_replication')
    @mock.patch.object(
        common.PowerMaxCommon, '_retype_volume',
        return_value=(True, tpd.PowerMaxData.defaultstoragegroup_name))
    @mock.patch.object(
        common.PowerMaxCommon, 'break_rdf_device_pair_session',
        return_value=({'mgmt_sg_name': tpd.PowerMaxData.rdf_managed_async_grp,
                       'rdf_group_no': tpd.PowerMaxData.rdf_group_no_1}, True))
    def test_migrate_volume_success_rep_to_no_rep(
            self, mck_break, mck_retype, mck_resume, mck_get, mck_valid):
        array_id = self.data.array
        volume = self.data.test_volume
        device_id = self.data.device_id
        srp = self.data.srp
        target_slo = self.data.slo_silver
        target_workload = self.data.workload
        volume_name = volume.name
        new_type = {'extra_specs': {}}
        extra_specs = self.data.rep_extra_specs

        target_extra_specs = {
            utils.SRP: srp, utils.ARRAY: array_id, utils.SLO: target_slo,
            utils.WORKLOAD: target_workload,
            utils.INTERVAL: extra_specs[utils.INTERVAL],
            utils.RETRIES: extra_specs[utils.RETRIES],
            utils.DISABLECOMPRESSION: False}

        success, model_update = self.common._migrate_volume(
            array_id, volume, device_id, srp, target_slo, target_workload,
            volume_name, new_type, extra_specs)
        mck_break.assert_called_once_with(
            array_id, device_id, volume_name, extra_specs)
        mck_retype.assert_called_once_with(
            array_id, srp, device_id, volume, volume_name, extra_specs,
            target_slo, target_workload, target_extra_specs)
        self.assertTrue(success)

    @mock.patch.object(common.PowerMaxCommon, '_validate_rdfg_status')
    @mock.patch.object(common.PowerMaxCommon, '_sync_check')
    @mock.patch.object(
        common.PowerMaxCommon, 'get_volume_metadata', return_value='')
    @mock.patch.object(
        common.PowerMaxCommon, '_post_retype_srdf_protect_storage_group',
        return_value=('Enabled', tpd.PowerMaxData.rdf_group_vol_details,
                      tpd.PowerMaxData.device_id2))
    @mock.patch.object(
        common.PowerMaxCommon, '_retype_volume',
        return_value=(True, tpd.PowerMaxData.defaultstoragegroup_name))
    @mock.patch.object(
        common.PowerMaxCommon, 'configure_volume_replication',
        return_value=('first_vol_in_rdf_group', {},
                      {'target_device_id': tpd.PowerMaxData.device_id2,
                       'remote_array': tpd.PowerMaxData.remote_array},
                      tpd.PowerMaxData.rep_extra_specs, False))
    def test_migrate_volume_success_no_rep_to_rep(
            self, mck_configure, mck_retype, mck_protect, mck_get, mck_check,
            mck_valid):
        self.common.rep_config = {'mode': utils.REP_SYNC,
                                  'array': self.data.array}
        array_id = self.data.array
        volume = deepcopy(self.data.test_volume)
        volume.id = self.data.volume_id
        device_id = self.data.device_id
        srp = self.data.srp
        target_slo = self.data.slo_silver
        target_workload = self.data.workload
        volume_name = volume.name
        updated_volume_name = self.utils.get_volume_element_name(volume.id)
        target_storage_group = self.data.defaultstoragegroup_name
        extra_specs = deepcopy(self.data.extra_specs)
        rep_config_sync = deepcopy(self.data.rep_config_sync)
        rep_config_sync[utils.RDF_CONS_EXEMPT] = False
        new_type = {'extra_specs': self.data.rep_extra_specs}

        target_extra_specs = deepcopy(new_type['extra_specs'])
        target_extra_specs.update({
            utils.SRP: srp, utils.ARRAY: array_id, utils.SLO: target_slo,
            utils.WORKLOAD: target_workload,
            utils.INTERVAL: extra_specs[utils.INTERVAL],
            utils.RETRIES: extra_specs[utils.RETRIES],
            utils.DISABLECOMPRESSION: False, utils.REP_MODE: utils.REP_SYNC,
            utils.REP_CONFIG: rep_config_sync})

        success, model_update = self.common._migrate_volume(
            array_id, volume, device_id, srp, target_slo, target_workload,
            volume_name, new_type, extra_specs)
        mck_configure.assert_called_once_with(
            array_id, volume, device_id, target_extra_specs)
        mck_retype.assert_called_once_with(
            array_id, srp, device_id, volume, volume_name, extra_specs,
            target_slo, target_workload, target_extra_specs)
        mck_protect.assert_called_once_with(
            array_id, target_storage_group, device_id, updated_volume_name,
            target_extra_specs)
        self.assertTrue(success)

    @mock.patch.object(common.PowerMaxCommon, '_validate_rdfg_status')
    @mock.patch.object(
        common.PowerMaxCommon, 'get_volume_metadata', return_value='')
    @mock.patch.object(
        common.PowerMaxCommon, '_retype_remote_volume', return_value=True)
    @mock.patch.object(
        common.PowerMaxCommon, '_retype_volume',
        return_value=(True, tpd.PowerMaxData.defaultstoragegroup_name))
    def test_migrate_volume_success_rep_to_rep(self, mck_retype, mck_remote,
                                               mck_get, mck_valid):
        self.common.rep_config = {'mode': utils.REP_SYNC,
                                  'array': self.data.array}
        array_id = self.data.array
        volume = self.data.test_volume
        device_id = self.data.device_id
        srp = self.data.srp
        target_slo = self.data.slo_silver
        target_workload = self.data.workload
        volume_name = volume.name
        rep_config_sync = deepcopy(self.data.rep_config_sync)
        rep_config_sync[utils.RDF_CONS_EXEMPT] = False
        extra_specs = deepcopy(self.data.rep_extra_specs)
        extra_specs[utils.SLO] = self.data.slo_diamond
        new_type = {'extra_specs': self.data.rep_extra_specs}

        target_extra_specs = deepcopy(new_type['extra_specs'])
        target_extra_specs.update({
            utils.SRP: srp, utils.ARRAY: array_id, utils.SLO: target_slo,
            utils.WORKLOAD: target_workload,
            utils.INTERVAL: extra_specs[utils.INTERVAL],
            utils.RETRIES: extra_specs[utils.RETRIES],
            utils.DISABLECOMPRESSION: False, utils.REP_MODE: utils.REP_SYNC,
            utils.REP_CONFIG: rep_config_sync})

        success, model_update = self.common._migrate_volume(
            array_id, volume, device_id, srp, target_slo, target_workload,
            volume_name, new_type, extra_specs)
        mck_retype.assert_called_once_with(
            array_id, srp, device_id, volume, volume_name, extra_specs,
            target_slo, target_workload, target_extra_specs)
        mck_remote.assert_called_once_with(
            array_id, volume, device_id, volume_name, utils.REP_SYNC,
            True, target_extra_specs)
        self.assertTrue(success)

    @mock.patch.object(masking.PowerMaxMasking, 'add_volume_to_storage_group')
    @mock.patch.object(provision.PowerMaxProvision, 'get_or_create_group')
    @mock.patch.object(utils.PowerMaxUtils, 'get_rdf_management_group_name',
                       return_value=tpd.PowerMaxData.rdf_managed_async_grp)
    def test_add_volume_to_rdf_management_group(self, mck_get_rdf, mck_get_grp,
                                                mck_add):
        array = self.data.array
        device_id = self.data.device_id
        volume_name = self.data.volume_id
        remote_array = self.data.remote_array
        target_device_id = self.data.device_id2
        extra_specs = deepcopy(self.data.rep_extra_specs)
        extra_specs[utils.REP_CONFIG] = self.data.rep_config_sync
        group_name = self.data.rdf_managed_async_grp

        get_create_grp_calls = [
            call(array, group_name, extra_specs),
            call(remote_array, group_name, extra_specs)]
        add_vol_calls = [
            call(array, device_id, group_name, volume_name, extra_specs,
                 force=True),
            call(remote_array, target_device_id, group_name, volume_name,
                 extra_specs, force=True)]

        self.common._add_volume_to_rdf_management_group(
            array, device_id, volume_name, remote_array, target_device_id,
            extra_specs)
        mck_get_grp.assert_has_calls(get_create_grp_calls)
        mck_add.assert_has_calls(add_vol_calls)

    @mock.patch.object(
        common.PowerMaxCommon, '_delete_from_srp')
    @mock.patch.object(
        rest.PowerMaxRest, 'srdf_resume_replication')
    @mock.patch.object(
        rest.PowerMaxRest, 'get_rdf_group',
        return_value=tpd.PowerMaxData.rdf_group_details)
    @mock.patch.object(
        masking.PowerMaxMasking, 'remove_and_reset_members')
    @mock.patch.object(
        provision.PowerMaxProvision, 'break_rdf_relationship')
    @mock.patch.object(
        rest.PowerMaxRest, 'get_storage_groups_from_volume',
        return_value=tpd.PowerMaxData.default_sg_re_enabled)
    @mock.patch.object(
        utils.PowerMaxUtils, 'get_rdf_management_group_name',
        return_value=tpd.PowerMaxData.rdf_managed_async_grp)
    @mock.patch.object(
        rest.PowerMaxRest, 'are_vols_rdf_paired',
        return_value=(True, None, utils.RDF_SYNC_STATE))
    def test_cleanup_remote_target_async_metro(
            self, mck_paired, mck_get_rdf, mck_get_sg, mck_break, mck_reset,
            mck_get_rdf_grp, mck_resume, mck_delete):
        array = self.data.array
        volume = self.data.test_volume
        remote_array = self.data.remote_array
        device_id = self.data.device_id
        target_device_id = self.data.device_id2
        rdf_group_no = self.data.rdf_group_no_1
        volume_name = self.data.volume_id
        rep_extra_specs = deepcopy(self.data.rep_extra_specs)
        rep_extra_specs[utils.REP_MODE] = utils.REP_METRO
        rep_extra_specs[utils.REP_CONFIG] = self.data.rep_config_metro
        sg_name = self.data.default_sg_re_enabled
        async_grp = self.data.rdf_managed_async_grp
        pair_state = utils.RDF_SYNC_STATE
        reset_calls = [
            call(remote_array, volume, target_device_id, volume_name,
                 rep_extra_specs, sg_name),
            call(remote_array, volume, target_device_id, volume_name,
                 rep_extra_specs, async_grp)]

        self.common._cleanup_remote_target(
            array, volume, remote_array, device_id, target_device_id,
            rdf_group_no, volume_name, rep_extra_specs)
        mck_paired.assert_called_once_with(
            array, remote_array, device_id, target_device_id)
        mck_get_rdf.assert_called_once_with(self.data.rep_config_metro)
        mck_get_sg.assert_called_once_with(array, device_id)
        mck_break.assert_called_once_with(
            array, device_id, sg_name, rdf_group_no, rep_extra_specs,
            pair_state)
        mck_reset.assert_has_calls(reset_calls)
        mck_get_rdf_grp.assert_called_once_with(array, rdf_group_no)
        mck_resume.assert_called_once_with(
            array, sg_name, rdf_group_no, rep_extra_specs)
        mck_delete.assert_called_once_with(
            remote_array, target_device_id, volume_name, rep_extra_specs)

    @mock.patch.object(
        common.PowerMaxCommon, '_delete_from_srp')
    @mock.patch.object(
        rest.PowerMaxRest, 'srdf_resume_replication')
    @mock.patch.object(
        rest.PowerMaxRest, 'get_rdf_group',
        return_value=tpd.PowerMaxData.rdf_group_details)
    @mock.patch.object(
        masking.PowerMaxMasking, 'remove_and_reset_members')
    @mock.patch.object(
        provision.PowerMaxProvision, 'break_rdf_relationship')
    @mock.patch.object(
        rest.PowerMaxRest, 'get_storage_groups_from_volume',
        return_value=tpd.PowerMaxData.default_sg_re_enabled)
    @mock.patch.object(
        rest.PowerMaxRest, 'are_vols_rdf_paired',
        return_value=(True, None, utils.RDF_SYNC_STATE))
    def test_cleanup_remote_target_sync(
            self, mck_paired, mck_get_sg, mck_break, mck_reset,
            mck_get_rdf_grp, mck_resume, mck_delete):
        array = self.data.array
        volume = self.data.test_volume
        remote_array = self.data.remote_array
        device_id = self.data.device_id
        target_device_id = self.data.device_id2
        rdf_group_no = self.data.rdf_group_no_1
        volume_name = self.data.volume_id
        rep_extra_specs = deepcopy(self.data.rep_extra_specs)
        rep_extra_specs[utils.REP_MODE] = utils.REP_SYNC
        sg_name = self.data.default_sg_re_enabled
        pair_state = utils.RDF_SYNC_STATE

        self.common._cleanup_remote_target(
            array, volume, remote_array, device_id, target_device_id,
            rdf_group_no, volume_name, rep_extra_specs)
        mck_paired.assert_called_once_with(
            array, remote_array, device_id, target_device_id)
        mck_get_sg.assert_called_once_with(array, device_id)
        mck_break.assert_called_once_with(
            array, device_id, sg_name, rdf_group_no, rep_extra_specs,
            pair_state)
        mck_reset.assert_called_once_with(
            remote_array, volume, target_device_id, volume_name,
            rep_extra_specs, sg_name)
        mck_get_rdf_grp.assert_called_once_with(array, rdf_group_no)
        mck_resume.assert_called_once_with(
            array, sg_name, rdf_group_no, rep_extra_specs)
        mck_delete.assert_called_once_with(
            remote_array, target_device_id, volume_name, rep_extra_specs)

    @mock.patch.object(
        rest.PowerMaxRest, 'get_storage_groups_from_volume',
        return_value=tpd.PowerMaxData.sg_list['storageGroupId'])
    @mock.patch.object(
        rest.PowerMaxRest, 'get_rdf_pair_volume',
        return_value=tpd.PowerMaxData.rdf_group_vol_details)
    @mock.patch.object(
        common.PowerMaxCommon, '_get_replication_extra_specs',
        return_value=tpd.PowerMaxData.rep_extra_specs)
    @mock.patch.object(
        common.PowerMaxCommon, 'get_rdf_details',
        return_value=(tpd.PowerMaxData.rdf_group_no_1,
                      tpd.PowerMaxData.remote_array))
    def test_cleanup_rdf_device_pair_vol_cnt_exception(
            self, mck_get_rdf, mck_get_rep, mck_get_rdf_pair, mck_get_sg_list):
        array = self.data.array
        rdf_group_no = self.data.rdf_group_no_1
        device_id = self.data.device_id
        extra_specs = deepcopy(self.data.rep_extra_specs)
        extra_specs[utils.REP_MODE] = utils.REP_SYNC
        extra_specs[utils.REP_CONFIG] = self.data.rep_config_sync
        self.assertRaises(
            exception.VolumeBackendAPIException,
            self.common.cleanup_rdf_device_pair, array, rdf_group_no,
            device_id, extra_specs)

    @mock.patch.object(
        rest.PowerMaxRest, 'srdf_resume_replication')
    @mock.patch.object(
        common.PowerMaxCommon, '_cleanup_rdf_storage_groups_post_r2_delete')
    @mock.patch.object(
        rest.PowerMaxRest, 'delete_volume')
    @mock.patch.object(
        rest.PowerMaxRest, 'remove_vol_from_sg')
    @mock.patch.object(
        rest.PowerMaxRest, 'srdf_remove_device_pair_from_storage_group')
    @mock.patch.object(
        rest.PowerMaxRest, 'srdf_suspend_replication')
    @mock.patch.object(
        rest.PowerMaxRest, 'get_num_vols_in_sg', return_value=2)
    @mock.patch.object(
        utils.PowerMaxUtils, 'get_rdf_management_group_name',
        return_value=tpd.PowerMaxData.rdf_managed_async_grp)
    @mock.patch.object(
        rest.PowerMaxRest, 'wait_for_rdf_pair_sync')
    @mock.patch.object(
        rest.PowerMaxRest, 'get_storage_groups_from_volume',
        return_value=tpd.PowerMaxData.sg_list_rep)
    @mock.patch.object(
        rest.PowerMaxRest, 'get_rdf_pair_volume',
        return_value=tpd.PowerMaxData.rdf_group_vol_details)
    @mock.patch.object(
        common.PowerMaxCommon, '_get_replication_extra_specs',
        return_value=tpd.PowerMaxData.rep_extra_specs_mgmt)
    @mock.patch.object(
        common.PowerMaxCommon, 'get_rdf_details',
        return_value=(tpd.PowerMaxData.rdf_group_no_1,
                      tpd.PowerMaxData.remote_array))
    def test_cleanup_rdf_device_pair(
            self, mck_get_rdf, mck_get_rep, mck_get_rdf_pair, mck_get_sg_list,
            mck_wait, mck_get_mgmt_grp, mck_get_num_vols, mck_suspend,
            mck_srdf_remove, mck_remove, mck_delete, mck_cleanup, mck_resume):
        array = self.data.array
        rdf_group_no = self.data.rdf_group_no_1
        device_id = self.data.device_id
        target_device_id = self.data.device_id2
        extra_specs = deepcopy(self.data.rep_extra_specs)
        extra_specs[utils.REP_MODE] = utils.REP_METRO
        extra_specs[utils.REP_CONFIG] = self.data.rep_config_metro
        rep_extra_specs = deepcopy(self.data.rep_extra_specs_mgmt)
        rdf_mgmt_grp = self.data.rdf_managed_async_grp

        self.common.cleanup_rdf_device_pair(
            array, rdf_group_no, device_id, extra_specs)

        remove_calls = [
            call(array, rdf_mgmt_grp, device_id, extra_specs),
            call(self.data.remote_array, rdf_mgmt_grp, target_device_id,
                 rep_extra_specs)]
        mck_suspend.assert_called_once_with(
            array, rdf_mgmt_grp, rdf_group_no, rep_extra_specs)
        mck_remove.assert_has_calls(remove_calls)
        mck_resume.assert_called_once_with(
            array, rdf_mgmt_grp, rdf_group_no, rep_extra_specs)

    @mock.patch.object(
        rest.PowerMaxRest, 'get_num_vols_in_sg', return_value=1)
    @mock.patch.object(
        common.PowerMaxCommon, '_get_replication_extra_specs',
        return_value=tpd.PowerMaxData.rep_extra_specs_mgmt)
    def test_prepare_replication_details(self, mck_get_rep, mck_get_vols):
        extra_specs = deepcopy(self.data.extra_specs_rep_enabled)
        extra_specs['workload'] = 'NONE'
        extra_specs['rep_mode'] = utils.REP_SYNC
        extra_specs[utils.REP_CONFIG] = self.data.rep_config_sync
        rep_extra_specs = self.data.rep_extra_specs_mgmt
        ref_info_dict = {
            'initial_device_list': ['00001', '00002'],
            'local_array': self.data.array,
            'rdf_group_no': self.data.rdf_group_no_1,
            'remote_array': self.data.remote_array,
            'rep_mode': utils.REP_SYNC, 'service_level': self.data.slo_diamond,
            'sg_name': self.data.default_sg_no_slo_re_enabled,
            'sync_interval': 2, 'sync_retries': 200}

        rep_first_vol, resp_extra_specs, rep_info_dict, rdfg_empty = (
            self.common.prepare_replication_details(extra_specs))
        self.assertFalse(rep_first_vol)
        self.assertEqual(rep_extra_specs, resp_extra_specs)
        self.assertEqual(ref_info_dict, rep_info_dict)
        self.assertFalse(rdfg_empty)

    @mock.patch.object(
        rest.PowerMaxRest, 'srdf_protect_storage_group')
    def test_srdf_protect_storage_group(self, mck_protect):
        extra_specs = self.data.rep_extra_specs
        rep_extra_specs = self.data.rep_extra_specs_mgmt
        volume_dict = {'storage_group': self.data.rdf_managed_async_grp}

        self.common.srdf_protect_storage_group(extra_specs, rep_extra_specs,
                                               volume_dict)
        mck_protect.assert_called_once_with(
            extra_specs['array'], rep_extra_specs['array'],
            rep_extra_specs['rdf_group_no'], extra_specs['rep_mode'],
            volume_dict['storage_group'], rep_extra_specs['slo'], extra_specs)

    def test_gather_replication_updates(self):
        self.common.rep_config = {
            'rdf_group_label': self.data.rdf_group_name_1}
        extra_specs = self.data.rep_extra_specs
        rep_extra_specs = deepcopy(self.data.rep_extra_specs_mgmt)
        rep_extra_specs[utils.REP_CONFIG] = self.data.rep_config_async
        volume_dict = {'storage_group': self.data.rdf_managed_async_grp,
                       'remote_device_id': self.data.device_id2,
                       'device_uuid': self.data.volume_id}
        ref_replication_update = (
            {'replication_status': common.REPLICATION_ENABLED,
             'replication_driver_data': six.text_type(
                 {'array': self.data.remote_array,
                  'device_id': self.data.device_id2})})

        replication_update, rep_info_dict = (
            self.common.gather_replication_updates(
                extra_specs, rep_extra_specs, volume_dict))

        self.assertEqual(ref_replication_update, replication_update)

    @mock.patch.object(
        common.PowerMaxCommon, '_delete_from_srp')
    @mock.patch.object(
        rest.PowerMaxRest, 'get_volumes_in_storage_group', return_value=0)
    @mock.patch.object(
        masking.PowerMaxMasking, 'remove_volume_from_sg')
    @mock.patch.object(
        rest.PowerMaxRest, 'srdf_delete_device_pair')
    @mock.patch.object(
        rest.PowerMaxRest, 'srdf_suspend_replication')
    @mock.patch.object(
        rest.PowerMaxRest, 'wait_for_rdf_group_sync')
    @mock.patch.object(
        rest.PowerMaxRest, 'get_storage_group_rdf_group_state',
        return_value=[utils.RDF_SYNCINPROG_STATE])
    @mock.patch.object(
        rest.PowerMaxRest, 'get_storage_groups_from_volume',
        side_effect=[tpd.PowerMaxData.r1_sg_list, tpd.PowerMaxData.r2_sg_list])
    @mock.patch.object(
        rest.PowerMaxRest, 'get_rdf_pair_volume',
        return_value=tpd.PowerMaxData.rdf_group_vol_details)
    @mock.patch.object(
        common.PowerMaxCommon, '_get_replication_extra_specs',
        return_value=tpd.PowerMaxData.ex_specs_rep_config[utils.REP_CONFIG])
    def test_break_rdf_device_pair_session_metro_async(
            self, mck_get_rep, mck_get_rdf, mck_get_sg, mck_get_sg_state,
            mck_wait, mck_suspend, mck_delete_rdf_pair, mck_remove,
            mck_get_vols, mck_delete):

        array = self.data.array
        device_id = self.data.device_id
        volume_name = self.data.test_volume.name
        extra_specs = deepcopy(self.data.ex_specs_rep_config)

        rep_extra_specs, resume_rdf = (
            self.common.break_rdf_device_pair_session(
                array, device_id, volume_name, extra_specs))

        extra_specs[utils.REP_CONFIG]['force_vol_remove'] = True
        self.assertEqual(extra_specs[utils.REP_CONFIG], rep_extra_specs)
        self.assertFalse(resume_rdf)

    @mock.patch.object(
        common.PowerMaxCommon, '_delete_from_srp')
    @mock.patch.object(
        rest.PowerMaxRest, 'get_volumes_in_storage_group', return_value=10)
    @mock.patch.object(
        masking.PowerMaxMasking, 'remove_volume_from_sg')
    @mock.patch.object(
        rest.PowerMaxRest, 'srdf_delete_device_pair')
    @mock.patch.object(
        rest.PowerMaxRest, 'srdf_suspend_replication')
    @mock.patch.object(
        rest.PowerMaxRest, 'wait_for_rdf_group_sync')
    @mock.patch.object(
        rest.PowerMaxRest, 'get_storage_group_rdf_group_state',
        return_value=[utils.RDF_SYNCINPROG_STATE])
    @mock.patch.object(
        rest.PowerMaxRest, 'get_storage_groups_from_volume',
        side_effect=[tpd.PowerMaxData.r1_sg_list, tpd.PowerMaxData.r2_sg_list])
    @mock.patch.object(
        rest.PowerMaxRest, 'get_rdf_pair_volume',
        return_value=tpd.PowerMaxData.rdf_group_vol_details)
    @mock.patch.object(
        common.PowerMaxCommon, '_get_replication_extra_specs',
        return_value=(
            tpd.PowerMaxData.ex_specs_rep_config_sync[utils.REP_CONFIG]))
    def test_break_rdf_device_pair_session_sync(
            self, mck_get_rep, mck_get_rdf, mck_get_sg, mck_get_sg_state,
            mck_wait, mck_suspend, mck_delete_rdf_pair, mck_remove,
            mck_get_vols, mck_delete):

        array = self.data.array
        device_id = self.data.device_id
        volume_name = self.data.test_volume.name
        extra_specs = deepcopy(self.data.ex_specs_rep_config)
        extra_specs[utils.REP_MODE] = utils.REP_SYNC
        extra_specs[utils.REP_CONFIG]['mode'] = utils.REP_SYNC

        rep_extra_specs, resume_rdf = (
            self.common.break_rdf_device_pair_session(
                array, device_id, volume_name, extra_specs))

        extra_specs[utils.REP_CONFIG]['force_vol_remove'] = True
        extra_specs[utils.REP_CONFIG]['mgmt_sg_name'] = (
            self.data.default_sg_no_slo_re_enabled)

        self.assertEqual(extra_specs[utils.REP_CONFIG], rep_extra_specs)
        self.assertTrue(resume_rdf)

    @mock.patch.object(
        provision.PowerMaxProvision, 'verify_slo_workload',
        return_value=(True, True))
    @mock.patch.object(utils.PowerMaxUtils, 'get_rdf_management_group_name',
                       return_value=tpd.PowerMaxData.rdf_managed_async_grp)
    @mock.patch.object(common.PowerMaxCommon,
                       '_validate_management_group_volume_consistency',
                       return_value=True)
    @mock.patch.object(common.PowerMaxCommon,
                       '_validate_storage_group_rdf_states',
                       side_effect=[True, True])
    @mock.patch.object(common.PowerMaxCommon,
                       '_validate_rdf_group_storage_group_exclusivity',
                       side_effect=[True, True])
    @mock.patch.object(common.PowerMaxCommon,
                       '_validate_storage_group_is_replication_enabled',
                       side_effect=[True, True])
    @mock.patch.object(rest.PowerMaxRest, 'get_storage_group',
                       return_value=tpd.PowerMaxData.sg_details[0])
    def test_validate_rdfg_status_success(
            self, mck_get, mck_is_rep, mck_is_excl, mck_states, mck_cons,
            mck_mgrp_name, mck_slo):
        array = self.data.array
        extra_specs = deepcopy(self.data.rep_extra_specs6)
        extra_specs[utils.REP_MODE] = utils.REP_ASYNC
        extra_specs[utils.REP_CONFIG] = self.data.rep_config_async
        management_sg_name = self.data.rdf_managed_async_grp
        rdfg = self.data.rdf_group_no_2
        mode = utils.REP_ASYNC

        self.common._validate_rdfg_status(array, extra_specs)

        self.assertEqual(2, mck_get.call_count)
        self.assertEqual(2, mck_is_rep.call_count)
        self.assertEqual(2, mck_is_excl.call_count)
        self.assertEqual(2, mck_states.call_count)
        self.assertEqual(1, mck_cons.call_count)
        self.assertEqual(1, mck_mgrp_name.call_count)
        mck_is_rep.assert_called_with(array, management_sg_name)
        mck_is_excl.assert_called_with(array, management_sg_name)
        mck_states.assert_called_with(array, management_sg_name, rdfg, mode)
        mck_cons.assert_called_with(array, management_sg_name, rdfg)

    @mock.patch.object(
        provision.PowerMaxProvision, 'verify_slo_workload',
        return_value=(True, True))
    @mock.patch.object(common.PowerMaxCommon,
                       '_validate_storage_group_rdf_states',
                       return_value=False)
    @mock.patch.object(common.PowerMaxCommon,
                       '_validate_rdf_group_storage_group_exclusivity',
                       return_value=True)
    @mock.patch.object(common.PowerMaxCommon,
                       '_validate_storage_group_is_replication_enabled',
                       return_value=True)
    @mock.patch.object(rest.PowerMaxRest, 'get_storage_group',
                       return_value=tpd.PowerMaxData.sg_details[0])
    def test_validate_rdfg_status_failure_default_sg(
            self, mck_get, mck_is_rep, mck_is_excl, mck_states, mck_slo):
        array = self.data.array
        extra_specs = deepcopy(self.data.rep_extra_specs6)
        extra_specs[utils.REP_MODE] = utils.REP_ASYNC
        extra_specs[utils.REP_CONFIG] = self.data.rep_config_async
        rdfg = self.data.rdf_group_no_2
        mode = utils.REP_ASYNC
        disable_compression = self.utils.is_compression_disabled(extra_specs)
        storage_group = self.utils.get_default_storage_group_name(
            extra_specs['srp'], extra_specs['slo'], extra_specs['workload'],
            disable_compression, True, extra_specs['rep_mode'])

        self.assertRaises(exception.VolumeBackendAPIException,
                          self.common._validate_rdfg_status,
                          array, extra_specs)

        self.assertEqual(1, mck_get.call_count)
        self.assertEqual(1, mck_is_rep.call_count)
        self.assertEqual(1, mck_is_excl.call_count)
        self.assertEqual(1, mck_states.call_count)
        mck_is_rep.assert_called_with(array, storage_group)
        mck_is_excl.assert_called_with(array, storage_group)
        mck_states.assert_called_with(array, storage_group, rdfg, mode)

    @mock.patch.object(
        provision.PowerMaxProvision, 'verify_slo_workload',
        return_value=(True, True))
    @mock.patch.object(utils.PowerMaxUtils, 'get_rdf_management_group_name',
                       return_value=tpd.PowerMaxData.rdf_managed_async_grp)
    @mock.patch.object(common.PowerMaxCommon,
                       '_validate_management_group_volume_consistency',
                       return_value=False)
    @mock.patch.object(common.PowerMaxCommon,
                       '_validate_storage_group_rdf_states',
                       side_effect=[True, True])
    @mock.patch.object(common.PowerMaxCommon,
                       '_validate_rdf_group_storage_group_exclusivity',
                       side_effect=[True, True])
    @mock.patch.object(common.PowerMaxCommon,
                       '_validate_storage_group_is_replication_enabled',
                       side_effect=[True, True])
    @mock.patch.object(rest.PowerMaxRest, 'get_storage_group',
                       return_value=tpd.PowerMaxData.sg_details[0])
    def test_validate_rdfg_status_failure_management_sg(
            self, mck_get, mck_is_rep, mck_is_excl, mck_states, mck_cons,
            mck_mgrp_name, mck_slo):
        array = self.data.array
        extra_specs = deepcopy(self.data.rep_extra_specs6)
        extra_specs[utils.REP_MODE] = utils.REP_ASYNC
        extra_specs[utils.REP_CONFIG] = self.data.rep_config_async
        management_sg_name = self.data.rdf_managed_async_grp
        rdfg = self.data.rdf_group_no_2
        mode = utils.REP_ASYNC

        self.assertRaises(exception.VolumeBackendAPIException,
                          self.common._validate_rdfg_status,
                          array, extra_specs)

        self.assertEqual(2, mck_get.call_count)
        self.assertEqual(2, mck_is_rep.call_count)
        self.assertEqual(2, mck_is_excl.call_count)
        self.assertEqual(2, mck_states.call_count)
        self.assertEqual(1, mck_cons.call_count)
        self.assertEqual(1, mck_mgrp_name.call_count)
        mck_is_rep.assert_called_with(array, management_sg_name)
        mck_is_excl.assert_called_with(array, management_sg_name)
        mck_states.assert_called_with(array, management_sg_name, rdfg, mode)
        mck_cons.assert_called_with(array, management_sg_name, rdfg)

    @mock.patch.object(rest.PowerMaxRest, 'get_storage_group_rep',
                       return_value={'rdf': True})
    def test_validate_storage_group_is_replication_enabled_success(
            self, mck_get):
        array = self.data.array
        storage_group = self.data.storagegroup_name_f
        is_valid = self.common._validate_storage_group_is_replication_enabled(
            array, storage_group)
        self.assertTrue(is_valid)
        mck_get.assert_called_once_with(array, storage_group)

    @mock.patch.object(rest.PowerMaxRest, 'get_storage_group_rep',
                       return_value={'rdf': False})
    def test_validate_storage_group_is_replication_enabled_failure(
            self, mck_get):
        array = self.data.array
        storage_group = self.data.storagegroup_name_f
        is_valid = self.common._validate_storage_group_is_replication_enabled(
            array, storage_group)
        self.assertFalse(is_valid)
        mck_get.assert_called_once_with(array, storage_group)

    @mock.patch.object(rest.PowerMaxRest, 'get_storage_group_rdf_group_state',
                       return_value=[utils.RDF_SYNC_STATE])
    def test_validate_storage_group_rdf_states_success(self, mck_get):
        array = self.data.array
        storage_group = self.data.storagegroup_name_f
        rdf_group_no = self.data.rdf_group_no_1
        rep_mode = utils.REP_SYNC
        is_valid = self.common._validate_storage_group_rdf_states(
            array, storage_group, rdf_group_no, rep_mode)
        self.assertTrue(is_valid)
        mck_get.assert_called_once_with(array, storage_group, rdf_group_no)

    @mock.patch.object(rest.PowerMaxRest, 'get_storage_group_rdf_group_state',
                       return_value=[utils.RDF_SYNC_STATE, utils.RDF_ACTIVE])
    def test_validate_storage_group_rdf_states_multi_async_state_failure(
            self, mck_get):
        array = self.data.array
        storage_group = self.data.storagegroup_name_f
        rdf_group_no = self.data.rdf_group_no_1
        rep_mode = utils.REP_ASYNC
        is_valid = self.common._validate_storage_group_rdf_states(
            array, storage_group, rdf_group_no, rep_mode)
        self.assertFalse(is_valid)
        mck_get.assert_called_once_with(array, storage_group, rdf_group_no)

    @mock.patch.object(rest.PowerMaxRest, 'get_storage_group_rdf_group_state',
                       return_value=['invalid_state'])
    def test_validate_storage_group_rdf_states_invalid_state_failure(
            self, mck_get):
        array = self.data.array
        storage_group = self.data.storagegroup_name_f
        rdf_group_no = self.data.rdf_group_no_1
        rep_mode = utils.REP_ASYNC
        is_valid = self.common._validate_storage_group_rdf_states(
            array, storage_group, rdf_group_no, rep_mode)
        self.assertFalse(is_valid)
        mck_get.assert_called_once_with(array, storage_group, rdf_group_no)

    @mock.patch.object(rest.PowerMaxRest, 'get_storage_group_rdf_groups',
                       return_value=[tpd.PowerMaxData.rdf_group_no_1])
    def test_validate_rdf_group_storage_group_exclusivity_success(
            self, mck_get):
        array = self.data.array
        storage_group = self.data.storagegroup_name_f
        is_valid = self.common._validate_rdf_group_storage_group_exclusivity(
            array, storage_group)
        self.assertTrue(is_valid)
        mck_get.assert_called_once_with(array, storage_group)

    @mock.patch.object(rest.PowerMaxRest, 'get_storage_group_rdf_groups',
                       return_value=[tpd.PowerMaxData.rdf_group_no_1,
                                     tpd.PowerMaxData.rdf_group_no_2])
    def test_validate_rdf_group_storage_group_exclusivity_failure(
            self, mck_get):
        array = self.data.array
        storage_group = self.data.storagegroup_name_f
        is_valid = self.common._validate_rdf_group_storage_group_exclusivity(
            array, storage_group)
        self.assertFalse(is_valid)
        mck_get.assert_called_once_with(array, storage_group)

    @mock.patch.object(rest.PowerMaxRest, 'get_volumes_in_storage_group',
                       return_value=[tpd.PowerMaxData.device_id])
    @mock.patch.object(rest.PowerMaxRest, 'get_rdf_group_volume_list',
                       return_value=[tpd.PowerMaxData.device_id])
    def test_validate_management_group_volume_consistency_success(
            self, mck_rdf, mck_sg):
        array = self.data.array
        storage_group = self.data.rdf_managed_async_grp
        rdf_group = self.data.rdf_group_no_1
        is_valid = self.common._validate_management_group_volume_consistency(
            array, storage_group, rdf_group)
        self.assertTrue(is_valid)
        mck_rdf.assert_called_once_with(array, rdf_group)
        mck_sg.assert_called_once_with(array, storage_group)

    @mock.patch.object(rest.PowerMaxRest, 'get_volumes_in_storage_group',
                       return_value=[tpd.PowerMaxData.device_id])
    @mock.patch.object(rest.PowerMaxRest, 'get_rdf_group_volume_list',
                       return_value=[tpd.PowerMaxData.device_id,
                                     tpd.PowerMaxData.device_id2])
    def test_validate_management_group_volume_consistency_failure(
            self, mck_rdf, mck_sg):
        array = self.data.array
        storage_group = self.data.rdf_managed_async_grp
        rdf_group = self.data.rdf_group_no_1
        is_valid = self.common._validate_management_group_volume_consistency(
            array, storage_group, rdf_group)
        self.assertFalse(is_valid)
        mck_rdf.assert_called_once_with(array, rdf_group)
        mck_sg.assert_called_once_with(array, storage_group)
