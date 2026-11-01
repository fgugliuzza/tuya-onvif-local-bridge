# SPDX-FileCopyrightText: 2026 Francesco Gugliuzza
# SPDX-License-Identifier: GPL-3.0-or-later

import base64
import datetime as dt
import hashlib
import hmac
import secrets
from lxml import etree as E

S = 'http://www.w3.org/2003/05/soap-envelope'
T = 'http://www.onvif.org/ver10/device/wsdl'
P = 'http://www.onvif.org/ver20/ptz/wsdl'
M = 'http://www.onvif.org/ver10/media/wsdl'
TT = 'http://www.onvif.org/ver10/schema'
W = 'http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd'
U = 'http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-utility-1.0.xsd'
NS = {'ter':'http://www.onvif.org/ver10/error', 's':S,'tds':T,'tptz':P,'trt':M,'tt':TT,'wsse':W,'wsu':U}

def el(parent, namespace, name, value=None, **attributes):
    child = E.SubElement(parent, '{%s}%s' % (namespace, name), **{k:str(v) for k,v in attributes.items()})
    if value is not None: child.text = str(value)
    return child

def envelope(namespace, name):
    root = E.Element('{%s}Envelope' % S, nsmap=NS)
    body = el(root,S,'Body')
    return root, el(body,namespace,name)

def xml(root): return E.tostring(root, encoding='utf-8', xml_declaration=True)

class Fault(Exception):
    def __init__(self, code='ter:ActionNotSupported', message='Operation not supported'):
        self.code, self.message = code, message
        super().__init__(message)

def fault_xml(fault):
    root, body = envelope(S,'Fault')
    code = el(body,S,'Code'); el(code,S,'Value','s:Sender')
    sub = el(code,S,'Subcode'); el(sub,S,'Value',fault.code)
    reason = el(body,S,'Reason'); el(reason,S,'Text',fault.message, **{'{http://www.w3.org/XML/1998/namespace}lang':'en'})
    return xml(root)

def read_request(data):
    parser = E.XMLParser(resolve_entities=False, no_network=True, remove_comments=True, huge_tree=False)
    root = E.fromstring(data, parser)
    body = root.find('{%s}Body' % S)
    if body is None or len(body) != 1: raise Fault('ter:InvalidArgVal','Invalid SOAP body')
    return root, body[0]

def field(node, name, default=None):
    found = node.xpath('.//*[local-name()=$n]', n=name)
    return found[0].text if found else default

def authenticate(root, config, nonce_cache):
    # ONVIF UsernameToken PasswordDigest = Base64(SHA1(nonce + created + password)).
    tokens = root.xpath('//*[local-name()="UsernameToken"]')
    if len(tokens) != 1: raise Fault('ter:NotAuthorized','Authentication required')
    token = tokens[0]
    username = field(token, 'Username')
    password = field(token, 'Password')
    nonce = field(token, 'Nonce')
    created = field(token, 'Created')
    if not username or password is None or not nonce or not created:
        raise Fault('ter:NotAuthorized','Incomplete UsernameToken')
    if not hmac.compare_digest(username, config.username): raise Fault('ter:NotAuthorized','Invalid credentials')
    try:
        stamp = dt.datetime.fromisoformat(created.replace('Z','+00:00'))
        if stamp.tzinfo is None or abs((dt.datetime.now(dt.timezone.utc)-stamp).total_seconds()) > 300:
            raise ValueError('Stale timestamp')
        nonce_bytes = base64.b64decode(nonce, validate=True)
        if not nonce_bytes: raise ValueError('Empty nonce')
    except (ValueError, TypeError): raise Fault('ter:NotAuthorized','Invalid nonce or timestamp')
    key = (username, nonce, created)
    if key in nonce_cache: raise Fault('ter:NotAuthorized','Replayed nonce')
    password_nodes = token.xpath('.//*[local-name()="Password"]')
    kind = password_nodes[0].get('Type', '') if password_nodes else ''
    if kind.endswith('#PasswordDigest'):
        expected = base64.b64encode(hashlib.sha1(nonce_bytes + created.encode() + config.password.encode()).digest()).decode()
    elif kind.endswith('#PasswordText'):
        expected = config.password
    else: raise Fault('ter:NotAuthorized','Unsupported password type')
    if not hmac.compare_digest(password, expected): raise Fault('ter:NotAuthorized','Invalid credentials')
    now = dt.datetime.now(dt.timezone.utc).timestamp()
    for k,v in list(nonce_cache.items()):
        if now-v > 600: del nonce_cache[k]
    nonce_cache[key] = now
