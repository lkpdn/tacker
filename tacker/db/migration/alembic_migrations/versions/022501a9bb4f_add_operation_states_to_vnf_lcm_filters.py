# Copyright 2020 OpenStack Foundation
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

"""add operation_states to vnf_lcm_filters

Revision ID: 022501a9bb4f
Revises: 329cd1619d41
Create Date: 2020-11-16 17:04:53.189925

"""

# flake8: noqa: E402

# revision identifiers, used by Alembic.
revision = '022501a9bb4f'
down_revision = '329cd1619d41'

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

from tacker.db import migration


def upgrade(active_plugins=None, options=None):
    sta_str = "json_unquote(json_extract('filter','$.operationStates'))"

    op.add_column(
        'vnf_lcm_filters',
        sa.Column('operation_states',
                  sa.LargeBinary(length=65536),
                  sa.Computed(sta_str)))
    op.add_column(
        'vnf_lcm_filters',
        sa.Column('operation_states_len',
                  sa.Integer,
                  sa.Computed("ifnull(json_length('operation_states'),0)")))
