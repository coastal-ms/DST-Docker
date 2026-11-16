"""Display authenticated portal links for the Linux host's IP addresses."""
import ipaddress
import sys
import socket
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


def primary_address():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as connection:
            connection.connect(('1.1.1.1', 53))
            return connection.getsockname()[0]
    except OSError:
        return None


def setup_links(local_url, host_address=None):
    # Select the host's route address, rather than every Docker bridge returned
    # by hostname -I. Never guess a bridge subnet or a second interface.
    links = portal_urls(local_url, [host_address] if host_address else [])
    text = 'Open setup on this PC:\n  ' + links[0]
    if len(links) > 1:
        text += '\n\nDirect Linux/WSL host address:\n  ' + links[1]
    return text


if __name__ == '__main__':
    local = sys.stdin.read()
    if sys.argv[1:2] == ['--display']:
        print(setup_links(local, primary_address()))
    elif sys.argv[1:2] == ['--https-origin']:
        parsed = urlsplit(portal_urls(local, [])[0])
        origin = urlsplit(sys.argv[2])
        if origin.scheme != 'https' or not origin.hostname or not origin.port or origin.path or origin.query or origin.fragment or origin.username:
            raise ValueError('The HTTPS origin is invalid.')
        print(urlunsplit(parsed._replace(scheme='https', netloc=origin.netloc)))
    else:
        print('\n'.join(portal_urls(local, sys.argv[1:])))
