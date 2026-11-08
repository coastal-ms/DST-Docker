"""Display authenticated portal links for the Linux host's IP addresses."""
import ipaddress
import sys
from urllib.parse import urlsplit, urlunsplit


def portal_urls(local_url, addresses):
    parsed = urlsplit(local_url.strip())
    if parsed.scheme != 'http' or parsed.hostname != '127.0.0.1' or not parsed.port:
        raise ValueError('The local portal address is invalid.')
    urls = [local_url.strip()]
    for value in addresses:
        try:
            address = ipaddress.ip_address(value)
        except ValueError:
            continue
        if address.version != 4 or address.is_loopback or address.is_unspecified or address.is_multicast or address.is_link_local:
            continue
        url = urlunsplit(parsed._replace(netloc=f'{address}:{parsed.port}'))
        if url not in urls:
            urls.append(url)
    return urls


if __name__ == '__main__':
    local = sys.stdin.read()
    if sys.argv[1:2] == ['--https-origin']:
        parsed = urlsplit(portal_urls(local, [])[0])
        origin = urlsplit(sys.argv[2])
        if origin.scheme != 'https' or not origin.hostname or not origin.port or origin.path or origin.query or origin.fragment or origin.username:
            raise ValueError('The HTTPS origin is invalid.')
        print(urlunsplit(parsed._replace(scheme='https', netloc=origin.netloc)))
    else:
        print('\n'.join(portal_urls(local, sys.argv[1:])))
