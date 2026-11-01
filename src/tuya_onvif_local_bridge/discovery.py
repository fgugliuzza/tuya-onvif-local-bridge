# SPDX-FileCopyrightText: 2026 Francesco Gugliuzza
# SPDX-License-Identifier: GPL-3.0-or-later

import asyncio
import logging
import socket
import uuid
from lxml import etree as E

log=logging.getLogger(__name__)
A='http://schemas.xmlsoap.org/ws/2004/08/addressing'
D='http://schemas.xmlsoap.org/ws/2005/04/discovery'
SOAP='http://www.w3.org/2003/05/soap-envelope'

class Discovery(asyncio.DatagramProtocol):
    def __init__(self, onvif): self.onvif=onvif; self.transport=None
    def connection_made(self, transport): self.transport=transport
    def datagram_received(self, data, addr):
        try:
            root=E.fromstring(data,E.XMLParser(resolve_entities=False,no_network=True))
            action=root.findtext('.//{%s}Action'%A,'')
            log.debug('WS-Discovery action=%s from %s',action,addr)
            if action.endswith('/Probe'):
                types=root.findtext('.//{%s}Types'%D,'')
                if types and not any(t.split(':')[-1] in ('NetworkVideoTransmitter','Device') for t in types.split()):
                    log.debug('Ignoring unsupported WS-Discovery types %r from %s',types,addr)
                    return
                self.reply('ProbeMatches','ProbeMatch',root,addr)
            elif action.endswith('/Resolve'):
                target=root.findtext('.//{%s}Resolve/{%s}EndpointReference/{%s}Address'%(D,A,A))
                if target==f'urn:uuid:{self.onvif.cfg.uuid}': self.reply('ResolveMatches','ResolveMatch',root,addr)
        except Exception: log.warning('Failed to handle WS-Discovery datagram from %s',addr,exc_info=True)
    def reply(self,operation,match,original,addr):
        ns={'s':SOAP,'a':A,'d':D,'dn':'http://www.onvif.org/ver10/network/wsdl'}
        root=E.Element('{%s}Envelope'%SOAP,nsmap=ns)
        head=E.SubElement(root,'{%s}Header'%SOAP)
        E.SubElement(head,'{%s}Action'%A).text=D+'/'+operation
        E.SubElement(head,'{%s}MessageID'%A).text='urn:uuid:'+str(uuid.uuid4())
        mid=original.findtext('.//{%s}MessageID'%A)
        if mid: E.SubElement(head,'{%s}RelatesTo'%A).text=mid
        body=E.SubElement(root,'{%s}Body'%SOAP)
        matches=E.SubElement(body,'{%s}%s'%(D,operation))
        m=E.SubElement(matches,'{%s}%s'%(D,match))
        ep=E.SubElement(m,'{%s}EndpointReference'%A)
        E.SubElement(ep,'{%s}Address'%A).text='urn:uuid:'+self.onvif.cfg.uuid
        E.SubElement(m,'{%s}Types'%D).text='dn:NetworkVideoTransmitter'
        E.SubElement(m,'{%s}Scopes'%D).text=' '.join(self.onvif.scopes())
        E.SubElement(m,'{%s}XAddrs'%D).text=self.onvif.url('device')
        E.SubElement(m,'{%s}MetadataVersion'%D).text='1'
        self.transport.sendto(E.tostring(root,encoding='utf-8',xml_declaration=True),addr)
        log.info('WS-Discovery %s sent to %s:%s',operation,*addr)

async def start_discovery(onvif):
    sock=socket.socket(socket.AF_INET,socket.SOCK_DGRAM,socket.IPPROTO_UDP)
    sock.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
    sock.bind(('',3702))
    group=socket.inet_aton('239.255.255.250')+socket.inet_aton(onvif.cfg.advertise_ip)
    try: sock.setsockopt(socket.IPPROTO_IP,socket.IP_ADD_MEMBERSHIP,group)
    except OSError:
        sock.setsockopt(socket.IPPROTO_IP,socket.IP_ADD_MEMBERSHIP,socket.inet_aton('239.255.255.250')+socket.inet_aton('0.0.0.0'))
    sock.setblocking(False)
    return await asyncio.get_running_loop().create_datagram_endpoint(lambda:Discovery(onvif),sock=sock)
