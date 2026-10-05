from __future__ import annotations

import html
import http.client
import ipaddress
import re
import socket
import ssl
import time
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit, urlunsplit

AGENT = 'R9700Hub/1.0 (+https://r9700.jjgo.io/about; read-only metadata collector)'


def safe_url(url: str, allowed_hosts=None) -> str:
    if not isinstance(url, str) or len(url) > 2048 or re.search(r'[\x00-\x20\\]', url):
        raise ValueError('invalid URL')
    parsed = urlsplit(url)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('only public HTTPS URLs without credentials are accepted')
    if parsed.port not in (None, 443):
        raise ValueError('nonstandard ports are blocked')
    host = parsed.hostname.lower().encode('idna').decode()
    if host in ('localhost', 'metadata.google.internal') or host.endswith(('.local','.localhost','.internal')):
        raise ValueError('private host is blocked')
    try:
        if not ipaddress.ip_address(host).is_global:
            raise ValueError('nonpublic address is blocked')
    except ValueError as error:
        if 'blocked' in str(error):
            raise
    if allowed_hosts is not None and host not in allowed_hosts:
        raise ValueError('host is not in the configured allowlist')
    return urlunsplit(('https',parsed.netloc,parsed.path or '/',parsed.query,''))


def public_addresses(host: str, resolver=socket.getaddrinfo):
    addresses = list(dict.fromkeys(entry[4][0] for entry in resolver(host,443,type=socket.SOCK_STREAM)))
    if not addresses or any(not ipaddress.ip_address(address).is_global for address in addresses):
        raise ValueError('DNS resolved a nonpublic address')
    return addresses


class _PinnedHTTPS(http.client.HTTPSConnection):
    def __init__(self, host, address, timeout):
        super().__init__(host,timeout=timeout,context=ssl.create_default_context())
        self.address = address

    def connect(self):
        raw = socket.create_connection((self.address,443),self.timeout)
        self.sock = self._context.wrap_socket(raw,server_hostname=self.host)


@dataclass
class Response:
    status: int
    url: str
    headers: dict
    body: bytes

    def text(self):
        match = re.search(r'charset\s*=\s*[\"\']?([\w-]+)',self.headers.get('content-type',''),re.I)
        if not match: match=re.search(r'charset\s*=\s*[\"\']?([\w-]+)',self.body[:4096].decode('ascii',errors='ignore'),re.I)
        charset = match.group(1) if match else 'utf-8'
        if charset.lower() in ('euc-kr','ks_c_5601-1987'): charset='cp949'
        return self.body.decode(charset,errors='replace')


class FetchError(Exception):
    def __init__(self, message, status=None, headers=None):
        super().__init__(message)
        self.status = status
        self.headers = headers or {}


class SafeClient:
    """No proxies, credential propagation, implicit redirects, or second DNS lookup."""
    def __init__(self, timeout=20, max_bytes=5*1024*1024, min_interval=2, resolver=None, connector=None):
        self.timeout = min(timeout,20)
        self.max_bytes = min(max_bytes,5*1024*1024)
        self.min_interval = min_interval
        self.last_origin = {}
        self.resolver = resolver or socket.getaddrinfo
        self.connector = connector or _PinnedHTTPS

    def get(self,url,allowed_hosts,headers=None,deadline=None):
        for redirect in range(4):
            url = safe_url(url,allowed_hosts)
            parsed = urlsplit(url); host = parsed.hostname
            addresses = public_addresses(host,self.resolver)
            delay = self.min_interval - (time.monotonic()-self.last_origin.get(host,0))
            if deadline and time.monotonic()+max(delay,0)+self.timeout > deadline:
                raise FetchError('time budget exhausted')
            if delay > 0:
                time.sleep(delay)
            self.last_origin[host] = time.monotonic()
            connection = self.connector(host,addresses[0],self.timeout)
            try:
                request_headers = {'User-Agent':AGENT,'Accept':'application/json, application/atom+xml, application/rss+xml, text/html;q=0.8,*/*;q=0.1','Accept-Encoding':'identity'}
                request_headers.update(headers or {})
                connection.request('GET',urlunsplit(('','',parsed.path,parsed.query,'')),headers=request_headers)
                response = connection.getresponse()
                response_headers = {key.lower():value for key,value in response.getheaders()}
                if response.status in (301,302,303,307,308):
                    if redirect == 3:
                        raise FetchError('redirect limit exceeded')
                    url = urljoin(url,response_headers.get('location',''))
                    continue
                if response.status == 304:
                    return Response(304,url,response_headers,b'')
                if response.status != 200:
                    raise FetchError(f'HTTP {response.status}',response.status,response_headers)
                if response_headers.get('content-encoding','identity') not in ('','identity'):
                    raise FetchError('unexpected compressed response')
                if int(response_headers.get('content-length','0')) > self.max_bytes:
                    raise FetchError('response exceeds byte limit')
                body = bytearray()
                started = time.monotonic()
                while True:
                    if time.monotonic()-started > self.timeout or (deadline and time.monotonic()>deadline):
                        raise FetchError('response time budget exceeded')
                    chunk = response.read(min(65536,self.max_bytes+1-len(body)))
                    if not chunk:
                        break
                    body.extend(chunk)
                    if len(body)>self.max_bytes:
                        raise FetchError('response exceeds byte limit')
                return Response(response.status,url,response_headers,bytes(body))
            except (OSError,http.client.HTTPException) as error:
                raise FetchError(type(error).__name__) from error
            finally:
                connection.close()
        raise FetchError('redirect limit exceeded')


class TextOnly(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts=[]; self.hidden=0
    def handle_starttag(self,tag,attrs):
        if tag in ('script','style','iframe','object','svg','template'):
            self.hidden += 1
        elif tag in ('p','br','div','li','h1','h2','h3'):
            self.parts.append('\n')
    def handle_endtag(self,tag):
        if tag in ('script','style','iframe','object','svg','template') and self.hidden:
            self.hidden-=1
    def handle_data(self,data):
        if not self.hidden:
            self.parts.append(data)


def plain_text(value,limit=8000):
    parser=TextOnly(); parser.feed(str(value)); parser.close()
    text=html.unescape(''.join(parser.parts))
    text=re.sub(r'\{[^{}]*\}', '', text) # never retain JSX expressions as executable-looking body
    text=re.sub(r'(?im)^\s*(?:import|export)\s+.*$','',text)
    return re.sub(r'[ \t]+',' ',text).strip()[:limit]


def relevant(text, source_kind='general'):
    normalized = re.sub(r'[™®_\-]+',' ',plain_text(text).lower())
    direct = bool(re.search(r'\br9700\b|radeon\s+(?:ai\s+pro|pro\s+ai)\s+9700|라데온\s*(?:ai|에이아이)?\s*프로\s*r?9700',normalized))
    if direct:
        return True
    if re.search(r'9700x|radeon\s+9700\s+pro|r9700s',normalized):
        return False
    if source_kind in ('rocm','therock'):
        return bool(re.search(r'gfx1201|rdna\s*4|radeon',normalized))
    return False
