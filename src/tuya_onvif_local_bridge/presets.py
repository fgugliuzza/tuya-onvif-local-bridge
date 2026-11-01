# SPDX-FileCopyrightText: 2026 Francesco Gugliuzza
# SPDX-License-Identifier: GPL-3.0-or-later

import asyncio
import json
import os
import tempfile
from pathlib import Path


class Registry:
    def __init__(self, path):
        self.path = Path(path)
        self.lock = asyncio.Lock()
        if self.path.exists():
            self.data = json.loads(self.path.read_text(encoding='utf-8'))
        else:
            self.data = {'schema_version': 1, 'presets': []}
        self.validate()

    def validate(self):
        d = self.data
        if not isinstance(d, dict) or d.get('schema_version') != 1 or not isinstance(d.get('presets'), list):
            raise ValueError('Invalid preset registry schema')
        tokens, ids = set(), set()
        for p in d['presets']:
            if not isinstance(p, dict) or type(p.get('seq')) is not int or p['seq'] <= 0:
                raise ValueError('Invalid preset seq')
            if p.get('mpId') != str(p['seq']):
                raise ValueError('Preset seq/mpId mismatch')
            if not isinstance(p.get('token'), str) or not p['token'] or not isinstance(p.get('name'), str):
                raise ValueError('Invalid preset token or name')
            if p['token'] in tokens or p['seq'] in ids:
                raise ValueError('Duplicate preset token or identifier')
            tokens.add(p['token']); ids.add(p['seq'])

    def next_id(self):
        used = {p['seq'] for p in self.data['presets']}
        n = 1
        while n in used:
            n += 1
        return n

    def find(self, token):
        return next((p for p in self.data['presets'] if p['token'] == token), None)

    def save(self):
        self.validate()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix='.presets-', dir=self.path.parent)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                json.dump(self.data, f, indent=2, ensure_ascii=False)
                f.write('\n'); f.flush(); os.fsync(f.fileno())
            os.replace(name, self.path)
            directory = os.open(self.path.parent, os.O_RDONLY)
            try: os.fsync(directory)
            finally: os.close(directory)
        finally:
            if os.path.exists(name): os.unlink(name)
