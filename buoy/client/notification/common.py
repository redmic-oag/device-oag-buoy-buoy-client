# -*- coding: utf-8 -*-

import json
import logging
import re
from enum import IntEnum, unique

from buoy.client.device.common.item import BaseItem, DataEncoder
from buoy.client.device.common.nmea0183 import WIMDA
from buoy.client.device.currentmeter.item import ACMPlusItem
from buoy.client.notification.exceptions import ValidationError

logger = logging.getLogger(__name__)


@unique
class NoticeType(IntEnum):
    NOTIFICATION = 1
    DATA = 2


class NotificationLevel(IntEnum):
    LOW = 10
    NORMAL = 5
    HIGHT = 3
    CRITICAL = 1


class NoticeBase(BaseItem):
    def __init__(self, notice_type: NoticeType, **kwargs):
        self.level = kwargs.pop('level', NotificationLevel.NORMAL)
        self.daemon = kwargs.pop('daemon', None)
        super(NoticeBase, self).__init__(**kwargs)
        self.type = notice_type

    @property
    def level(self):
        """
        :return: Notice level
        :rtype: Enum
        """
        return self._level

    @level.setter
    def level(self, value):
        if type(value) is NotificationLevel:
            value = value.value

        self._level = value

    @property
    def type(self):
        """
        :return: Notice type
        :rtype: Enum
        """
        return self._type

    @type.setter
    def type(self, value):
        if type(value) is NoticeType:
            value = value.value

        self._type = value

    @property
    def daemon(self):
        return self._daemon

    @daemon.setter
    def daemon(self, value):
        self._daemon = value

    def to_json(self):
        return json.dumps(self, sort_keys=True, cls=DataEncoder)

    def __str__(self):
        return "{datetime} - {level} - {type}".format(**dict(self))


class NoticeData(NoticeBase):
    def __init__(self, **kwargs):
        self.data = kwargs.pop('data', None)
        self.device = kwargs.pop('device', None)
        super(NoticeData, self).__init__(notice_type=NoticeType.DATA, **kwargs)

    @property
    def data(self):
        """
        :return: Notification level
        :rtype: Enum
        """
        return self._data

    @data.setter
    def data(self, input):
        value = None
        cls = type(input)
        if issubclass(cls, BaseItem):
            value = input
        elif type(input) is dict:
            if self.device == 'ACMPlus':
                value = ACMPlusItem(input)
            elif self.device == 'PB200':
                value = WIMDA(input)

        self._data = value

    @property
    def device(self):
        return self._device

    @device.setter
    def device(self, value: str):
        self._device = value


class Notification(NoticeBase):
    def __init__(self, message: str, **kwargs):
        self.phone = kwargs.pop('phone', None)
        super(Notification, self).__init__(notice_type=NoticeType.NOTIFICATION, **kwargs)
        self.message = message

    @property
    def message(self):
        """
        :return: Message
        :rtype: Decimal
        """
        return self._message

    @message.setter
    def message(self, value):
        self._message = value

    @property
    def phone(self):
        return self._phone

    @phone.setter
    def phone(self, value):
        if value:
            self.validate_mobile(value)
        self._phone = value

    @staticmethod
    def validate_mobile(value):
        """ Raise a ValidationError if the value looks like a mobile telephone number.
        """
        rule = re.compile(r'^(?:\+?34)?\d{9,13}$|^\d{4}$')

        if not rule.search(value):
            msg = u"Invalid mobile number."
            raise ValidationError(msg)

    def __str__(self):
        return "{datetime} - {level} - {type} - {message} - {phone}".format(**dict(self))
