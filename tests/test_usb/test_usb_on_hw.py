import pytest
from pathlib import Path
import serial.tools.list_ports

from tests.conftest import ON_HW_TESTS

FIXTURES_PATH = Path(__file__).parent / "fixtures"

vid=0x20B1
pid=0x4000
max_read_size=4096

@pytest.mark.skipif(not ON_HW_TESTS, reason="Hardware tests disabled")
def test_usb_cdc_on_hw():
    all_ports = serial.tools.list_ports.comports()
    test_ports = []
    required_ports = 2

    for port in all_ports:
        if port.vid == vid and port.pid == pid:
            test_ports.append(port)

    assert len(test_ports) == required_ports, f'Expected {required_ports} serial ports, found { len(test_ports) }.'

    try:
        port0 = serial.Serial(test_ports[0].device)
        port1 = serial.Serial(test_ports[1].device)

        from_file_str = b""
        from_port_str = b""
        with open( FIXTURES_PATH / "cdc_text.txt", "rb") as in_file:
            while 1:
                tx_data = in_file.read(max_read_size)

                if not tx_data:
                    break

                port0.write(tx_data)
                from_file_str += tx_data
                from_port_str += port1.read(len(tx_data))
    except Exception as e:
        raise e
    finally:
        if port0 is not None:
            port0.close()
        if port1 is not None:
            port1.close()
        
    assert from_file_str == from_port_str


