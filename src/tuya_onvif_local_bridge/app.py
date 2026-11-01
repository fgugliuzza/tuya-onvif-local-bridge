# SPDX-FileCopyrightText: 2026 Francesco Gugliuzza
# SPDX-License-Identifier: GPL-3.0-or-later

import asyncio
import logging
import os
import signal
from aiohttp import web
from .config import Config
from .presets import Registry
from .tuya import TuyaCamera
from .onvif import Onvif
from .discovery import start_discovery

log=logging.getLogger(__name__)

async def serve():
    cfg=Config.from_env()
    registry=Registry(cfg.data_path)
    camera=TuyaCamera(cfg)
    await camera.connect()
    onvif=Onvif(cfg,camera,registry)
    app=web.Application(client_max_size=65536)
    for service in ('device','media','ptz'):
        app.router.add_post(f'/onvif/{service}_service',onvif.handler)
    async def health(request): return web.json_response({'status':'ok' if not camera.dead else 'unavailable'},status=200 if not camera.dead else 503)
    app.router.add_get('/healthz',health)
    runner=web.AppRunner(app); await runner.setup()
    site=web.TCPSite(runner,'0.0.0.0',cfg.port); await site.start()
    discovery_transport=None
    try:
        discovery_transport,_=await start_discovery(onvif)
        log.info('ONVIF %s ready on %s, UUID %s',cfg.name,onvif.url('device'),cfg.uuid)
        stop=asyncio.Event()
        for sig in (signal.SIGINT,signal.SIGTERM):
            asyncio.get_running_loop().add_signal_handler(sig,stop.set)
        while not stop.is_set():
            if camera.dead: raise RuntimeError('Camera connection unrecoverable')
            try: await asyncio.wait_for(stop.wait(),timeout=.25)
            except asyncio.TimeoutError: pass
    finally:
        if discovery_transport: discovery_transport.close()
        await camera.close()
        await runner.cleanup()

def main():
    logging.basicConfig(level=os.getenv('LOG_LEVEL','INFO').upper(),format='%(asctime)s %(levelname)s %(name)s: %(message)s')
    try: asyncio.run(serve())
    except Exception:
        log.exception('Fatal error; exiting for container restart')
        raise SystemExit(1)

if __name__=='__main__': main()
