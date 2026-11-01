# SPDX-FileCopyrightText: 2026 Francesco Gugliuzza
# SPDX-License-Identifier: GPL-3.0-or-later

import asyncio
import json
import logging
import time

log = logging.getLogger(__name__)

class TuyaError(Exception): pass
class TuyaTransportError(TuyaError): pass
class TuyaRejected(TuyaError): pass


def parse_ack(dps, expected):
    raw = dps.get('178')
    if not isinstance(raw, str):
        return False
    try:
        payload = json.loads(raw)
        return (type(payload.get('type')) is int and payload['type'] == expected and
                type(payload.get('data', {}).get('error')) is int and payload['data']['error'] == 0)
    except (ValueError, TypeError, AttributeError):
        return False


class TuyaCamera:
    def __init__(self, config, factory=None):
        self.config = config
        self.factory = factory
        self.lock = asyncio.Lock()
        self.device = None
        self.moving = False
        self.dead = False
        self.stop_task = None
        self.on_reconnect = None

    def _new_device(self):
        if self.factory:
            return self.factory()
        import tinytuya
        d = tinytuya.Device(self.config.device_id, self.config.ip, self.config.local_key, version=float(self.config.version))
        d.set_socketTimeout(5)
        d.set_socketPersistent(False)
        return d

    def _connect_sync(self):
        if self.device:
            try: self.device.close()
            except Exception: pass
        self.device = self._new_device()
        result = self.device.status()
        self._check_transport(result)
        if not isinstance(result, dict) or not isinstance(result.get('dps'), dict):
            raise TuyaTransportError('No DPS returned by camera')
        return result

    @staticmethod
    def _check_transport(result):
        if isinstance(result, dict) and ('Error' in result or 'Err' in result):
            raise TuyaTransportError('TinyTuya error: ' + str(result.get('Err', 'unknown')))
        if result is None:
            raise TuyaTransportError('Empty TinyTuya response')

    async def connect(self):
        for attempt in range(self.config.reconnect_attempts + 1):
            try:
                await asyncio.to_thread(self._connect_sync)
                log.info('Tuya connection established')
                return
            except (Exception) as exc:
                log.warning('Tuya connection attempt %d failed: %s', attempt + 1, type(exc).__name__)
                if attempt >= self.config.reconnect_attempts:
                    self.dead = True
                    raise TuyaTransportError('Tuya reconnect attempts exhausted') from exc
                await asyncio.sleep(self.config.reconnect_delay)

    async def _recover(self):
        try:
            await self.connect()
            if self.on_reconnect is not None:
                # Do not delay or fail PTZ recovery for a metadata refresh.
                try:
                    self.on_reconnect()
                except Exception:
                    log.warning('RTSP metadata refresh scheduling failed')
            if self.moving:
                try: await asyncio.to_thread(self._set_sync, '116', True)
                except Exception: log.warning('Best-effort stop after reconnect failed')
                self.moving = False
        except TuyaTransportError:
            self.dead = True
            raise

    def _set_sync(self, dp, value):
        result = self.device.set_value(int(dp), value)
        self._check_transport(result)
        return result

    def _set_sync_allow_empty(self, dp, value):
        # Only used for DP178 type=3. None is ambiguous: it may represent the
        # observed empty cmd=13 reply or a genuine timeout. Never generalize
        # this exception to preset creation or other DP writes.
        result = self.device.set_value(int(dp), value)
        if result is not None:
            self._check_transport(result)
        return result

    def _status_sync(self):
        result = self.device.status()
        self._check_transport(result)
        if not isinstance(result, dict) or not isinstance(result.get('dps'), dict):
            raise TuyaTransportError('Invalid status response')
        return result['dps']

    async def _io(self, fn, *args):
        if self.dead:
            raise TuyaTransportError('Camera is offline')
        try:
            return await asyncio.to_thread(fn, *args)
        except TuyaTransportError:
            await self._recover()
            raise
        except (OSError, TimeoutError, ConnectionError) as exc:
            await self._recover()
            raise TuyaTransportError('Transport failure') from exc

    async def preset(self, operation, data):
        async with self.lock:
            request = json.dumps({'type': operation, 'data': data}, separators=(',', ':'))
            before = (await self._io(self._status_sync)).get('178')
            # TinyTuya can return the new DPS state directly from set_value().
            # Inspect it before polling: the camera may overwrite DP178 with an
            # unrelated notification before the first status() request.
            if operation == 3:
                # This camera replies to a recall with a valid Tuya cmd=13 frame
                # carrying an empty payload. TinyTuya consumes that frame and
                # returns None after its receive timeout. A missing application
                # acknowledgement must not cause an automatic second movement.
                # Explicit TinyTuya errors still raise via _check_transport.
                write_result = await self._io(self._set_sync_allow_empty, '178', request)
                if write_result is None:
                    log.debug('Preset recall sent; TinyTuya returned no application response '
                                '(outcome unconfirmed, no retry)')
                    return
            else:
                write_result = await self._io(self._set_sync, '178', request)

            def check(dps):
                if not isinstance(dps, dict):
                    return False
                raw = dps.get('178')
                if not isinstance(raw, str) or raw == before:
                    return False  # Never accept a latched acknowledgement.
                try:
                    response = json.loads(raw)
                except (ValueError, TypeError):
                    return False
                if not isinstance(response, dict) or response.get('type') != operation:
                    return False
                if parse_ack(dps, operation):
                    return True
                raise TuyaRejected('DP178 operation returned an error or malformed acknowledgement')

            if isinstance(write_result, dict) and check(write_result.get('dps')):
                return
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                if check(await self._io(self._status_sync)):
                    return
                await asyncio.sleep(.15)
            raise TuyaRejected('Missing fresh matching DP178 acknowledgement')

    async def move(self, direction, seconds):
        async with self.lock:
            if self.stop_task:
                self.stop_task.cancel(); self.stop_task = None
            if self.moving:
                await self._io(self._set_sync, '116', True)
                self.moving = False
            await self._io(self._set_sync, '119', self.config.direction_codes[direction])
            self.moving = True
            self.stop_task = asyncio.create_task(self._stop_later(seconds))

    async def _stop_later(self, seconds):
        try:
            await asyncio.sleep(seconds)
            await self.stop()
        except asyncio.CancelledError:
            pass
        except Exception:
            log.exception('Automatic PTZ stop failed')

    async def stop(self):
        async with self.lock:
            task = self.stop_task
            self.stop_task = None
            if task and task is not asyncio.current_task(): task.cancel()
            await self._io(self._set_sync, '116', True)
            self.moving = False

    async def before_preset(self):
        if self.moving:
            await self.stop()

    async def close(self):
        if self.stop_task: self.stop_task.cancel()
        if self.moving:
            try: await self.stop()
            except Exception: pass
        if self.device:
            try: await asyncio.to_thread(self.device.close)
            except Exception: pass
