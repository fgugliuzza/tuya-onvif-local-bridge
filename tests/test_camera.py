# SPDX-FileCopyrightText: 2026 Francesco Gugliuzza
# SPDX-License-Identifier: GPL-3.0-or-later

import json
from types import SimpleNamespace
import pytest
from tuya_onvif_local_bridge.tuya import TuyaCamera, TuyaRejected

class Fake:
    def __init__(self): self.last=None; self.value='{"type":2,"data":{"error":0}}'
    def status(self): return {'dps':{'178':self.value}}
    def set_value(self,dp,value):
        self.last=(dp,value)
        payload=json.loads(value)
        self.value=json.dumps({'type':payload['type'],'data':{'error':0}})
        return {'dps':{'178':self.value}}
    def close(self): pass

@pytest.mark.asyncio
async def test_preset_ack():
    fake=Fake()
    cfg=SimpleNamespace(reconnect_attempts=0,reconnect_delay=0, direction_codes={})
    camera=TuyaCamera(cfg,lambda:fake)
    await camera.connect()
    await camera.preset(1,{'seq':1})
    assert fake.last[0]==178
    # An identical old acknowledgement cannot be attributed to a new invocation.
    with pytest.raises(TuyaRejected):
        await camera.preset(1,{'seq':1})


@pytest.mark.asyncio
async def test_ack_only_in_write_response():
    class TransientAck(Fake):
        def set_value(self, dp, value):
            result = super().set_value(dp, value)
            self.value = '{"type":4,"data":{"Time":1793543615}}'
            return result

    fake = TransientAck()
    camera = TuyaCamera(SimpleNamespace(reconnect_attempts=0, reconnect_delay=0), lambda: fake)
    await camera.connect()
    await camera.preset(1, {'name': 'ACKTEST01', 'seq': 1})
    assert fake.last[0] == 178


@pytest.mark.asyncio
async def test_ack_from_poll_after_unrelated_write_response():
    class DelayedAck(Fake):
        def set_value(self, dp, value):
            super().set_value(dp, value)
            return {'dps': {'178': '{"type":4,"data":{"Time":1793543615}}'}}

    fake = DelayedAck()
    camera = TuyaCamera(SimpleNamespace(reconnect_attempts=0, reconnect_delay=0), lambda: fake)
    await camera.connect()
    await camera.preset(1, {'seq': 1})


@pytest.mark.asyncio
async def test_stale_write_ack_is_not_accepted():
    class StaleAck(Fake):
        def set_value(self, dp, value):
            self.last = (dp, value)
            return {'dps': {'178': self.value}}

    fake = StaleAck()
    fake.value = '{"type":1,"data":{"error":0}}'
    camera = TuyaCamera(SimpleNamespace(reconnect_attempts=0, reconnect_delay=0), lambda: fake)
    await camera.connect()
    with pytest.raises(TuyaRejected, match='Missing fresh'):
        await camera.preset(1, {'seq': 1})
