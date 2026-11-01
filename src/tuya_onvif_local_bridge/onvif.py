# SPDX-FileCopyrightText: 2026 Francesco Gugliuzza
# SPDX-License-Identifier: GPL-3.0-or-later

import asyncio
import datetime as dt
import logging
import math
import re
from aiohttp import web
from lxml import etree as E
from .soap import S,T,P,M,TT,NS,el,envelope,xml,fault_xml,Fault,read_request,field,authenticate
from .tuya import TuyaError, TuyaTransportError
from .rtsp_probe import StreamInfo

log = logging.getLogger(__name__)

class Onvif:
    def __init__(self, config, camera, registry):
        self.cfg, self.camera, self.registry = config, camera, registry
        self.nonces = {}
        self.stream_info = StreamInfo()
        self.profile = 'profile_1'
        self.ptzconfig = 'ptz_1'
        self.node = 'node_1'

    def url(self, service):
        return f'http://{self.cfg.advertise_ip}:{self.cfg.port}/onvif/{service}_service'

    async def handler(self, request):
        try:
            raw = await request.read()
            if len(raw) > 65536: raise Fault('ter:InvalidArgVal','SOAP request too large')
            root, action = read_request(raw)
            # GetSystemDateAndTime and GetServices are usable before authentication for discovery.
            if E.QName(action).localname not in ('GetSystemDateAndTime', 'GetServices'):
                authenticate(root, self.cfg, self.nonces)
            name = E.QName(action).localname
            path = request.path
            service = 'device' if 'device_service' in path else 'ptz' if 'ptz_service' in path else 'media'
            result = await getattr(self, f'{service}_{name}', self.unsupported)(action)
            return web.Response(body=xml(result), content_type='application/soap+xml')
        except Fault as exc:
            return web.Response(status=500, body=fault_xml(exc), content_type='application/soap+xml')
        except TuyaTransportError:
            log.exception('Tuya transport error')
            return web.Response(status=500, body=fault_xml(Fault('ter:Action','Camera unavailable')), content_type='application/soap+xml')
        except TuyaError as exc:
            return web.Response(status=500, body=fault_xml(Fault('ter:Action',str(exc))), content_type='application/soap+xml')
        except (E.XMLSyntaxError, ValueError) as exc:
            return web.Response(status=400, body=fault_xml(Fault('ter:InvalidArgVal','Invalid request')), content_type='application/soap+xml')
        except Exception:
            log.exception('Unexpected ONVIF error')
            return web.Response(status=500, body=fault_xml(Fault('ter:Action','Internal error')), content_type='application/soap+xml')

    async def unsupported(self, action): raise Fault()

    async def device_GetSystemDateAndTime(self, action):
        root,r=envelope(T,'GetSystemDateAndTimeResponse')
        x=el(r,T,'SystemDateAndTime'); el(x,TT,'DateTimeType','NTP'); el(x,TT,'DaylightSavings','false')
        now=dt.datetime.now(dt.timezone.utc)
        utc=el(x,TT,'UTCDateTime'); t=el(utc,TT,'Time')
        for n,v in [('Hour',now.hour),('Minute',now.minute),('Second',now.second)]: el(t,TT,n,v)
        d=el(utc,TT,'Date')
        for n,v in [('Year',now.year),('Month',now.month),('Day',now.day)]: el(d,TT,n,v)
        return root

    async def device_GetDeviceInformation(self, action):
        root,r=envelope(T,'GetDeviceInformationResponse')
        for n,v in [('Manufacturer','Tuya ONVIF Bridge'),('Model','Tuya PTZ Bridge'),('FirmwareVersion','0.1.8'),('SerialNumber',self.cfg.device_id),('HardwareId',self.cfg.uuid)]: el(r,T,n,v)
        return root

    async def device_GetServices(self, action):
        root,r=envelope(T,'GetServicesResponse')
        for ns,name in [(T,'device'),(M,'media'),(P,'ptz')]:
            s=el(r,T,'Service'); el(s,T,'Namespace',ns); el(s,T,'XAddr',self.url(name)); ver=el(s,T,'Version'); el(ver,TT,'Major',2 if name=='ptz' else 1); el(ver,TT,'Minor',0)
        return root

    async def device_GetCapabilities(self, action):
        root,r=envelope(T,'GetCapabilitiesResponse'); cap=el(r,T,'Capabilities')
        device=el(cap,TT,'Device'); el(device,TT,'XAddr',self.url('device'))
        media=el(cap,TT,'Media'); el(media,TT,'XAddr',self.url('media'))
        streaming=el(media,TT,'StreamingCapabilities')
        el(streaming,TT,'RTPMulticast','false')
        el(streaming,TT,'RTP_TCP','true')
        el(streaming,TT,'RTP_RTSP_TCP','true')
        ptz=el(cap,TT,'PTZ'); el(ptz,TT,'XAddr',self.url('ptz'))
        return root

    async def device_GetScopes(self, action):
        root,r=envelope(T,'GetScopesResponse')
        for scope in self.scopes():
            s=el(r,T,'Scopes'); el(s,TT,'ScopeDef','Fixed'); el(s,TT,'ScopeItem',scope)
        return root

    def scopes(self):
        from urllib.parse import quote
        return ['onvif://www.onvif.org/type/video_encoder','onvif://www.onvif.org/type/ptz',
                'onvif://www.onvif.org/name/'+quote(self.cfg.name, safe=''),
                'onvif://www.onvif.org/hardware/TuyaPTZBridge']

    async def device_GetHostname(self, action):
        root,r=envelope(T,'GetHostnameResponse'); h=el(r,T,'HostnameInformation'); el(h,TT,'FromDHCP','false'); el(h,TT,'Name',self.cfg.name); return root

    def _video_source_config(self, parent, element='VideoSourceConfiguration', namespace=TT):
        v=el(parent,namespace,element,token='video_source_config_1')
        el(v,TT,'Name','Camera source'); el(v,TT,'UseCount',1); el(v,TT,'SourceToken','video_source_1')
        el(v,TT,'Bounds',x=0,y=0,width=self.stream_info.width,height=self.stream_info.height)
        return v

    def _video_encoder_config(self, parent, element='VideoEncoderConfiguration', namespace=TT):
        v=el(parent,namespace,element,token='video_encoder_config_1')
        el(v,TT,'Name','RTSP '+self.stream_info.codec); el(v,TT,'UseCount',1)
        el(v,TT,'Encoding',self.stream_info.codec)
        r=el(v,TT,'Resolution'); el(r,TT,'Width',self.stream_info.width); el(r,TT,'Height',self.stream_info.height)
        el(v,TT,'Quality',5)
        rate=el(v,TT,'RateControl'); el(rate,TT,'FrameRateLimit',max(1,round(self.stream_info.fps))); el(rate,TT,'EncodingInterval',1); el(rate,TT,'BitrateLimit',self.stream_info.bitrate_kbps)
        if self.stream_info.codec == 'H264':
            h=el(v,TT,'H264'); el(h,TT,'GovLength',self.stream_info.gop or 30); el(h,TT,'H264Profile',self.stream_info.profile)
        # ONVIF requires Multicast before SessionTimeout, even for unicast-only devices.
        multicast=el(v,TT,'Multicast')
        address=el(multicast,TT,'Address')
        el(address,TT,'Type','IPv4'); el(address,TT,'IPv4Address','0.0.0.0')
        el(multicast,TT,'Port',0); el(multicast,TT,'TTL',0); el(multicast,TT,'AutoStart','false')
        el(v,TT,'SessionTimeout','PT60S')
        return v

    def _profile(self, parent, element='Profiles'):
        p=el(parent,M,element,token=self.profile,fixed='true')
        el(p,TT,'Name',self.cfg.name)
        self._video_source_config(p)
        self._video_encoder_config(p)
        self._ptz_config(p)
        return p

    async def media_GetProfiles(self, action):
        root,r=envelope(M,'GetProfilesResponse'); self._profile(r); return root

    async def media_GetProfile(self, action):
        self._validate_profile(action)
        root,r=envelope(M,'GetProfileResponse'); self._profile(r, 'Profile'); return root

    def _validate_profile(self, action):
        if field(action,'ProfileToken') not in (None,self.profile): raise Fault('ter:NoProfile','Unknown profile')

    async def media_GetVideoSources(self, action):
        root,r=envelope(M,'GetVideoSourcesResponse'); v=el(r,M,'VideoSources',token='video_source_1'); el(v,TT,'Framerate',max(1,round(self.stream_info.fps)))
        res=el(v,TT,'Resolution'); el(res,TT,'Width',self.stream_info.width); el(res,TT,'Height',self.stream_info.height)
        return root

    async def media_GetVideoSourceConfigurations(self, action):
        root,r=envelope(M,'GetVideoSourceConfigurationsResponse'); self._video_source_config(r, 'Configurations', M); return root

    async def media_GetVideoSourceConfiguration(self, action):
        if field(action,'ConfigurationToken') != 'video_source_config_1': raise Fault('ter:InvalidArgVal','Unknown video source configuration')
        root,r=envelope(M,'GetVideoSourceConfigurationResponse'); self._video_source_config(r, 'Configuration', M); return root

    async def media_GetVideoEncoderConfigurations(self, action):
        root,r=envelope(M,'GetVideoEncoderConfigurationsResponse'); self._video_encoder_config(r, 'Configurations', M); return root

    async def media_GetVideoEncoderConfiguration(self, action):
        if field(action,'ConfigurationToken') != 'video_encoder_config_1': raise Fault('ter:InvalidArgVal','Unknown video encoder configuration')
        root,r=envelope(M,'GetVideoEncoderConfigurationResponse'); self._video_encoder_config(r, 'Configuration', M); return root

    async def media_GetVideoEncoderConfigurationOptions(self, action):
        root,r=envelope(M,'GetVideoEncoderConfigurationOptionsResponse')
        opts=el(r,M,'Options'); el(opts,TT,'QualityRange')
        quality=opts[-1]; el(quality,TT,'Min',1); el(quality,TT,'Max',10)
        if self.stream_info.codec == 'H264':
            h=el(opts,TT,'H264'); resolutions=el(h,TT,'ResolutionsAvailable'); el(resolutions,TT,'Width',self.stream_info.width); el(resolutions,TT,'Height',self.stream_info.height)
            for name,low,high in [('GovLengthRange',1,300),('FrameRateRange',1,max(1,round(self.stream_info.fps))),('EncodingIntervalRange',1,1)]:
                rng=el(h,TT,name); el(rng,TT,'Min',low); el(rng,TT,'Max',high)
            el(h,TT,'H264ProfilesSupported',self.stream_info.profile)
        return root

    async def media_GetServiceCapabilities(self, action):
        root,r=envelope(M,'GetServiceCapabilitiesResponse')
        capabilities=el(r,M,'Capabilities',SnapshotUri='false',Rotation='false',VideoSourceMode='false',OSD='false')
        el(capabilities,M,'ProfileCapabilities',MaximumNumberOfProfiles=1)
        el(capabilities,M,'StreamingCapabilities',RTPMulticast='false',RTP_TCP='true',RTP_RTSP_TCP='true')
        return root

    async def media_GetStreamUri(self, action):
        self._validate_profile(action)
        root,r=envelope(M,'GetStreamUriResponse'); u=el(r,M,'MediaUri')
        el(u,TT,'Uri',self.cfg.stream_uri); el(u,TT,'InvalidAfterConnect','false'); el(u,TT,'InvalidAfterReboot','false'); el(u,TT,'Timeout','PT0S')
        return root

    def _spaces(self, parent, element='SupportedPTZSpaces'):
        # ContinuousPanTiltVelocitySpace with ONVIF standard generic coordinate space.
        spaces=el(parent,TT,element)
        s=el(spaces,TT,'ContinuousPanTiltVelocitySpace')
        el(s,TT,'URI','http://www.onvif.org/ver10/tptz/PanTiltSpaces/VelocityGenericSpace')
        for axis in ('XRange','YRange'):
            a=el(s,TT,axis); el(a,TT,'Min',-1); el(a,TT,'Max',1)

    async def ptz_GetNodes(self, action):
        root,r=envelope(P,'GetNodesResponse'); self._node(r, 'PTZNode', P); return root

    async def ptz_GetNode(self, action):
        if field(action,'NodeToken') != self.node: raise Fault('ter:InvalidArgVal','Unknown PTZ node')
        root,r=envelope(P,'GetNodeResponse'); self._node(r, 'PTZNode', P); return root

    def _node(self, parent, element='PTZNode', namespace=TT):
        node=el(parent,namespace,element,token=self.node,FixedHomePosition='false')
        el(node,TT,'Name','Tuya PTZ'); self._spaces(node); el(node,TT,'MaximumNumberOfPresets',255); el(node,TT,'HomeSupported','false')

    async def ptz_GetConfigurations(self, action):
        root,r=envelope(P,'GetConfigurationsResponse'); self._ptz_config(r, 'PTZConfiguration', P); return root

    async def ptz_GetConfiguration(self, action):
        if field(action,'PTZConfigurationToken') != self.ptzconfig: raise Fault('ter:InvalidArgVal','Unknown PTZ configuration')
        root,r=envelope(P,'GetConfigurationResponse'); self._ptz_config(r, 'PTZConfiguration', P); return root

    def _ptz_config(self, parent, element='PTZConfiguration', namespace=TT):
        c=el(parent,namespace,element,token=self.ptzconfig)
        el(c,TT,'Name','PTZ'); el(c,TT,'UseCount',1); el(c,TT,'NodeToken',self.node)
        el(c,TT,'DefaultContinuousPanTiltVelocitySpace','http://www.onvif.org/ver10/tptz/PanTiltSpaces/VelocityGenericSpace')
        el(c,TT,'DefaultPTZTimeout',f'PT{self.cfg.default_timeout:g}S')

    async def ptz_GetConfigurationOptions(self, action):
        root,r=envelope(P,'GetConfigurationOptionsResponse'); o=el(r,P,'PTZConfigurationOptions')
        self._spaces(o, 'Spaces'); t=el(o,TT,'PTZTimeout'); el(t,TT,'Min','PT0.1S'); el(t,TT,'Max',f'PT{self.cfg.max_timeout:g}S')
        return root

    async def ptz_GetPresets(self, action):
        self._validate_profile(action)
        root,r=envelope(P,'GetPresetsResponse')
        for preset in self.registry.data['presets']:
            p=el(r,P,'Preset',token=preset['token']); el(p,TT,'Name',preset['name'])
        return root

    async def ptz_SetPreset(self, action):
        self._validate_profile(action)
        if field(action,'PresetToken') is not None: raise Fault('ter:ActionNotSupported','Preset overwriting is not implemented')
        name=field(action,'PresetName')
        if not name or len(name)>10: raise Fault('ter:InvalidArgVal','Preset name must be 1-10 characters')
        await self.camera.before_preset()
        async with self.registry.lock:
            if any(p['name']==name for p in self.registry.data['presets']):
                raise Fault('ter:InvalidArgVal','Duplicate preset name')
            n=self.registry.next_id()
            await self.camera.preset(1,{'name':name,'seq':n,'pan':0,'tilt':0,'zoom':0})
            token=f'preset-{n}'
            self.registry.data['presets'].append({'token':token,'seq':n,'mpId':str(n),'name':name,'pan':None,'tilt':None,'zoom':None})
            self.registry.save()
        root,r=envelope(P,'SetPresetResponse'); el(r,P,'PresetToken',token); return root

    async def ptz_GotoPreset(self, action):
        self._validate_profile(action)
        token=field(action,'PresetToken')
        async with self.registry.lock:
            preset=self.registry.find(token)
            if not preset: raise Fault('ter:NoPreset','Unknown preset')
            await self.camera.before_preset()
            await self.camera.preset(3,{'mpId':preset['mpId']})
        root,r=envelope(P,'GotoPresetResponse'); return root

    async def ptz_RemovePreset(self, action): raise Fault('ter:ActionNotSupported','Preset deletion is not implemented')

    async def ptz_ContinuousMove(self, action):
        self._validate_profile(action)
        velocity=action.xpath('.//*[local-name()="Velocity"]/*[local-name()="PanTilt"]')
        if len(velocity)!=1: raise Fault('ter:InvalidArgVal','PanTilt velocity required')
        try:
            x=float(velocity[0].get('x')); y=float(velocity[0].get('y'))
            if not math.isfinite(x) or not math.isfinite(y) or abs(x)>1 or abs(y)>1: raise ValueError()
        except (ValueError, TypeError): raise Fault('ter:InvalidArgVal','Invalid velocity')
        if abs(x)<0.01 and abs(y)<0.01: await self.camera.stop()
        else:
            horizontal='right' if x>0 else 'left' if x<0 else ''
            vertical='up' if y>0 else 'down' if y<0 else ''
            direction=vertical + ('-' if vertical and horizontal else '') + horizontal
            raw=field(action,'Timeout')
            if raw:
                match=re.fullmatch(r'PT(\d+(?:\.\d+)?)S',raw)
                if not match: raise Fault('ter:InvalidArgVal','Invalid duration')
                seconds=float(match.group(1))
            else: seconds=self.cfg.default_timeout
            if seconds<=0 or seconds>self.cfg.max_timeout: raise Fault('ter:InvalidArgVal','Movement timeout out of range')
            await self.camera.move(direction,seconds)
        root,r=envelope(P,'ContinuousMoveResponse'); return root

    async def ptz_Stop(self, action):
        self._validate_profile(action)
        await self.camera.stop()
        root,r=envelope(P,'StopResponse'); return root
