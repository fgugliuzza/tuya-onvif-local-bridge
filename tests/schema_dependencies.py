# SPDX-FileCopyrightText: 2026 Francesco Gugliuzza
# SPDX-License-Identifier: GPL-3.0-or-later

"""External ONVIF schema imports: namespace -> (local path, canonical URL)."""
EXTERNAL_SCHEMAS = {
    'http://www.w3.org/XML/1998/namespace': ('www.w3.org/2001/xml.xsd', 'https://www.w3.org/2001/xml.xsd'),
    'http://www.w3.org/2005/05/xmlmime': ('www.w3.org/2005/05/xmlmime', 'https://www.w3.org/2005/05/xmlmime'),
    'http://www.w3.org/2003/05/soap-envelope': ('www.w3.org/2003/05/soap-envelope', 'https://www.w3.org/2003/05/soap-envelope'),
    'http://www.w3.org/2004/08/xop/include': ('www.w3.org/2004/08/xop/include', 'https://www.w3.org/2004/08/xop/include'),
    'http://www.w3.org/2005/08/addressing': ('www.w3.org/2005/08/addressing/ws-addr.xsd', 'https://www.w3.org/2005/08/addressing/ws-addr.xsd'),
    'http://docs.oasis-open.org/wsn/b-2': ('docs.oasis-open.org/wsn/b-2.xsd', 'https://docs.oasis-open.org/wsn/b-2.xsd'),
    'http://docs.oasis-open.org/wsn/t-1': ('docs.oasis-open.org/wsn/t-1.xsd', 'https://docs.oasis-open.org/wsn/t-1.xsd'),
    'http://docs.oasis-open.org/wsrf/bf-2': ('docs.oasis-open.org/wsrf/bf-2.xsd', 'https://docs.oasis-open.org/wsrf/bf-2.xsd'),
}
