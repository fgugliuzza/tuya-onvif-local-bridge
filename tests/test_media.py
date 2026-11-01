# SPDX-FileCopyrightText: 2026 Francesco Gugliuzza
# SPDX-License-Identifier: GPL-3.0-or-later

from types import SimpleNamespace
import pytest
from lxml import etree
from tuya_onvif_local_bridge.config import Config
from tuya_onvif_local_bridge.onvif import Onvif

@pytest.fixture
def env(monkeypatch):
    for key, value in {'TUYA_DEVICE_ID':'abc','TUYA_LOCAL_KEY':'secret','TUYA_IP':'192.168.0.22','TUYA_VERSION':'3.5','ONVIF_USERNAME':'admin','ONVIF_PASSWORD':'secret','ONVIF_ADVERTISE_IP':'192.168.0.104'}.items():
        monkeypatch.setenv(key,value)
    monkeypatch.delenv('ONVIF_STREAM_URI',raising=False)


def test_required_rtsp_uri(env,monkeypatch):
    with pytest.raises(ValueError,match='ONVIF_STREAM_URI'):
        Config.from_env()
    monkeypatch.setenv('ONVIF_STREAM_URI','http://example.com/video')
    with pytest.raises(ValueError,match='ONVIF_STREAM_URI'):
        Config.from_env()
    monkeypatch.setenv('ONVIF_STREAM_URI','rtsp://192.168.0.22:554/live')
    assert Config.from_env().stream_uri == 'rtsp://192.168.0.22:554/live'

@pytest.mark.asyncio
async def test_media_profile_and_uri(env,monkeypatch):
    monkeypatch.setenv('ONVIF_STREAM_URI','rtsp://192.168.0.22/live')
    onvif=Onvif(Config.from_env(),None,None)
    request=etree.fromstring(b'<GetStreamUri><ProfileToken>profile_1</ProfileToken></GetStreamUri>')
    profiles=await onvif.media_GetProfiles(request)
    assert len(profiles.xpath('//*[local-name()="Profiles"]')) == 1
    assert len(profiles.xpath('//*[local-name()="VideoEncoderConfiguration"]')) == 1
    assert len(profiles.xpath('//*[local-name()="PTZConfiguration"]')) == 1
    response=await onvif.media_GetStreamUri(request)
    assert response.xpath('//*[local-name()="Uri"]')[0].text == 'rtsp://192.168.0.22/live'
