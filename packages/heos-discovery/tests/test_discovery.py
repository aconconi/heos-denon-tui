from heos_discovery import _Protocol


def test_reply_is_parsed_into_a_device():
    protocol = _Protocol()
    protocol.datagram_received(
        b"HTTP/1.1 200 OK\r\nLOCATION: http://192.168.1.39:60006/upnp/desc/aios_device/aios_device.xml\r\n"
        b"SERVER: Linux UPnP/1.0 Denon-Heos/1.0\r\nUSN: uuid:abc::urn:schemas-denon-com:device:ACT-Denon:1\r\n\r\n",
        ("192.168.1.39", 1900),
    )
    (device,) = protocol.devices.values()
    assert device.host == "192.168.1.39"
    assert "Denon" in device.server


def test_reply_without_location_falls_back_to_sender_address():
    protocol = _Protocol()
    protocol.datagram_received(b"HTTP/1.1 200 OK\r\nUSN: x\r\n\r\n", ("10.0.0.5", 1900))
    assert list(protocol.devices) == ["10.0.0.5"]
