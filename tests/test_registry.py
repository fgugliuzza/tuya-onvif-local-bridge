# SPDX-FileCopyrightText: 2026 Francesco Gugliuzza
# SPDX-License-Identifier: GPL-3.0-or-later

import json
import pytest
from tuya_onvif_local_bridge.presets import Registry

def test_gap_and_invariant(tmp_path):
    path=tmp_path/'presets.json'
    path.write_text(json.dumps({'schema_version':1,'presets':[{'token':f'preset-{n}','seq':n,'mpId':str(n),'name':str(n)} for n in (1,2,4)]}))
    r=Registry(path)
    assert r.next_id()==3
    r.data['presets'][0]['mpId']='99'
    with pytest.raises(ValueError): r.save()

def test_corrupt_fails(tmp_path):
    path=tmp_path/'presets.json'; path.write_text('broken')
    with pytest.raises(json.JSONDecodeError): Registry(path)
