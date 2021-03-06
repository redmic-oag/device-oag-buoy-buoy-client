import unittest
from queue import Queue
from unittest.mock import MagicMock
from unittest.mock import patch

from nose.tools import eq_
from serial import SerialException

from buoy.client.device.common.base import DeviceReader
from buoy.client.device.common.exceptions import ProcessDataExecption
from buoy.client.notification.client.common import NoticePriorityQueue

serial_config = {
    'port': '/dev/weather_station',
    'baudrate': 4800,
    'stopbits': 1,
    'parity': 'N',
    'bytesize': 8,
    'timeout': 0
}

device = MagicMock()


class DeviceReaderMock(DeviceReader):
    def __init__(self, **kwargs):
        super(DeviceReaderMock, self).__init__(**kwargs)

    def parser(self, data):
        return data


class TestItemReaderThread(unittest.TestCase):
    def setUp(self):
        self.queue_save_data = Queue()
        self.queue_notice = NoticePriorityQueue()
        self.thread = DeviceReaderMock(queue_save_data=self.queue_save_data, queue_notice=self.queue_notice,
                                       device=device)

    def test_returnTwoItems_when_passStringWith3CarriageReturnAndWhiteSpace(self):
        text = """hola
            
        adios"""

        lines = self.thread.split_by_lines(text)

        eq_(len(lines), 2)

    def test_bufferContainsJoinTwoText_when_callTwoRead_Data(self):
        text = [b"Hola", b" como esta"]

        self.thread.device.read = MagicMock(side_effect=text)

        self.thread.read_data()
        self.thread.read_data()

        eq_(self.thread.buffer, "Hola como esta")

    def test_stopThread_when_deviceRaiseException(self):
        self.thread.active = True
        self.thread.read_data = MagicMock(side_effect=OSError())

        self.thread.start()
        self.thread.join(timeout=60)

        eq_(self.thread.active, False)
        eq_(self.thread.queue_notice.qsize(), 1)

    def test_returnFalse_when_charSplitterIsInBuffer(self):
        text = """hola

        adios"""

        self.thread.buffer = text

        eq_(self.thread.is_buffer_empty(), False)

    def test_returnTrue_when_charSplitterIsNotInBuffer(self):
        text = """hola"""

        self.thread.buffer = text

        eq_(self.thread.is_buffer_empty(), True)

    @patch.object(DeviceReader, 'read_data', side_effect=SerialException())
    @patch.object(DeviceReader, 'error')
    def test_shouldStopThread_when_raiseExceptionInReadDataMethod(self, mock_read, mock_error):
        self.thread.active = True
        self.thread.activity()
        eq_(mock_error.call_count, 1)

    def test_returnArrray2ItemsAndBufferRestOfString_when_bufferHas2SplitCharAndMoreData(self):
        text = """hola
        adios
        bye"""

        self.thread.buffer = text
        self.thread.process_data()

        eq_(self.thread.queue_save_data.qsize(), 2)
        eq_(self.thread.buffer, "bye")

    def test_returnArrray2ItemsAndBufferEmpty_when_bufferHas2SplitCharOnly(self):
        text = """hola
        adios
"""

        self.thread.buffer = text
        self.thread.process_data()

        eq_(self.thread.queue_save_data.qsize(), 2)
        eq_(len(self.thread.buffer), 0)

    def test_returnException_when_bufferHasNotSplitChar(self):
        text = """hola"""
        self.thread.buffer = text

        self.assertRaises(ProcessDataExecption, self.thread.process_data)


if __name__ == '__main__':
    unittest.main()
