"""SSDP discovery of HEOS devices (CLI protocol spec section 2)."""

from __future__ import annotations

import asyncio
import socket
from dataclasses import dataclass
from urllib.parse import urlparse

SSDP_ADDR = ("239.255.255.250", 1900)
SEARCH_TARGET = "urn:schemas-denon-com:device:ACT-Denon:1"


@dataclass(frozen=True)
class DiscoveredDevice:
    host: str
    location: str
    usn: str = ""
    server: str = ""


class _Protocol(asyncio.DatagramProtocol):
    def __init__(self) -> None:
        self.devices: dict[str, DiscoveredDevice] = {}

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        headers = {}
        for line in data.decode(errors="replace").split("\r\n")[1:]:
            key, _, value = line.partition(":")
            headers[key.strip().lower()] = value.strip()
        location = headers.get("location", "")
        host = urlparse(location).hostname or addr[0]
        self.devices[host] = DiscoveredDevice(
            host=host,
            location=location,
            usn=headers.get("usn", ""),
            server=headers.get("server", ""),
        )


async def discover(
    timeout: float = 3.0, *, stop_after_first: bool = False
) -> list[DiscoveredDevice]:
    """Send an SSDP M-SEARCH and collect replies for ``timeout`` seconds.

    Every HEOS speaker answers; any one of them can be used as the connection point.
    With ``stop_after_first`` returns as soon as one device has replied.
    """
    loop = asyncio.get_running_loop()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
    sock.setblocking(False)
    transport, protocol = await loop.create_datagram_endpoint(_Protocol, sock=sock)
    request = (
        "M-SEARCH * HTTP/1.1\r\n"
        f"HOST: {SSDP_ADDR[0]}:{SSDP_ADDR[1]}\r\n"
        'MAN: "ssdp:discover"\r\n'
        "MX: 2\r\n"
        f"ST: {SEARCH_TARGET}\r\n\r\n"
    )
    try:
        transport.sendto(request.encode(), SSDP_ADDR)
        deadline = loop.time() + timeout
        while loop.time() < deadline and not (stop_after_first and protocol.devices):
            await asyncio.sleep(0.1)
    finally:
        transport.close()
    return list(protocol.devices.values())
