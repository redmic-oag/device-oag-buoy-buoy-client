import unittest
from datetime import datetime, timezone
from queue import Queue
from unittest.mock import patch

from nose.tools import ok_

from buoy.client.device.weatherstation.pb200 import PB200Reader, WIMDA


class TestACMPlusReader(unittest.TestCase):
    def setUp(self):
        self.date = datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f%z"),
        self.data = {
            'id': None,
            'date': self.date,
            'air_temp': '26.8',
            'press_inch': '30.3273',
            'press_bar': '1.027',
            'water_temp': '20.1',
            'rel_humidity': '12.3',
            'abs_humidity': '21.0',
            'dew_point': '2.3',
            'wind_dir_true': '2.0',
            'wind_dir_magnetic': '128.7',
            'wind_knots': '134.6',
            'wind_meters': '0.3'
        }

        self.item_expected = WIMDA(**self.data)

    @patch('buoy.client.device.common.base.Device')
    def test_should_returnItem_when_parseWIMDASentence(self, mock_device):
        line = "$WIMDA,{press_inch},I,{press_bar},B,{air_temp},C," \
               "{water_temp},C,{rel_humidity},{abs_humidity},{dew_point},C," \
               "{wind_dir_true},T,{wind_dir_magnetic},M,{wind_knots},N," \
               "{wind_meters},M*28".format(**self.data)
        reader = PB200Reader(device=mock_device, queue_save_data=Queue(), queue_notice=Queue(),
                             queue_exceptions=Queue())
        item = reader.parser(line)
        item._date = self.date

        ok_(item == self.item_expected)


if __name__ == '__main__':
    unittest.main()
