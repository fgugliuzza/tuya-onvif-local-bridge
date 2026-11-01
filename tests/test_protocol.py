# SPDX-FileCopyrightText: 2026 Francesco Gugliuzza
# SPDX-License-Identifier: GPL-3.0-or-later

import json
from tuya_onvif_local_bridge.tuya import parse_ack
from tuya_onvif_local_bridge.soap import envelope, xml, read_request, T

def test_ack_types():
    assert parse_ack({'178':json.dumps({'type':1,'data':{'error':0}})},1)
    assert not parse_ack({'178':json.dumps({'type':2,'data':{'error':0}})},1)
    assert not parse_ack({'178':json.dumps({'type':1,'data':{'error':3}})},1)
    assert not parse_ack({'178':'garbage'},1)

def test_soap():
    root, action=envelope(T,'GetServices')
    parsed, op=read_request(xml(root))
    assert op.tag.endswith('GetServices')
