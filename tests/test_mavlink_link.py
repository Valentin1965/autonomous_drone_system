"""mavlink.link — gcs_radio vs rpi_usb."""

from mavlink.runtime_config import client_connection_string, mavlink_link_description


def test_gcs_radio_connection():
    cfg = {
        "role": "ground_station",
        "mavlink": {
            "active": "px4",
            "link": "gcs_radio",
            "connection_gcs": "udp:10.0.0.1:14550",
            "connection_px4": "udp:fallback:14550",
        },
    }
    assert client_connection_string(cfg) == "udp:10.0.0.1:14550"
    assert "GCS radio" in mavlink_link_description(cfg)


def test_rpi_usb_connection():
    cfg = {
        "role": "rpi_companion",
        "mavlink": {
            "active": "px4",
            "link": "rpi_usb",
            "connection_rpi": "serial:/dev/ttyACM0:115200",
        },
    }
    assert client_connection_string(cfg) == "serial:/dev/ttyACM0:115200"
    assert "RPi USB" in mavlink_link_description(cfg)
