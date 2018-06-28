# -*- coding: utf-8 -*-

import json
import logging
from datetime import datetime, timezone
from decimal import *

from dateutil import parser

logger = logging.getLogger(__name__)


class BaseItem(object):
    def __init__(self, **kwargs):
        self.id = kwargs.pop('id', None)
        self.date = kwargs.pop('date', datetime.now(tz=timezone.utc))

    @property
    def id(self):
        """
        :return: Identifier
        :rtype: Integer
        """
        return self._id

    @id.setter
    def id(self, value):
        self._id = value

    @property
    def date(self):
        """
        :return: Datetime
        :rtype: Datetime
        """
        return self._date

    @date.setter
    def date(self, value):
        if type(value) is int:
            value = datetime.fromtimestamp(value / 1000.0)
        elif type(value) is str:
            value = parser.parse(value)

        self._date = value

    @staticmethod
    def _convert_string_to_decimal(value):
        val = None
        if value is not None:
            try:
                val = Decimal(value)
            except InvalidOperation:
                logger.error("Convert string to decimal", value)

        return val

    def to_json(self):
        item = json.dumps(self, cls=DataEncoder, sort_keys=True, separators=(',', ':'))
        return item

    def __iter__(self):
        for name in dir(self):
            yield name, getattr(self, name)

    def __dir__(self):
        list_props = []
        for name in vars(self):
            list_props.append(name[1:])

        return list_props

    def __eq__(self, other):
        if isinstance(other, self.__class__):
            a = dict(other)
            b = dict(self)
            return a == b
        return False

    def __lt__(self, other):
        if isinstance(other, self.__class__):
            return self.date < other.date

    def __str__(self):
        line = ''
        for name in dir(self):
            line += '%s: %s | ' % (name, getattr(self, name))


class DataEncoder(json.JSONEncoder):
    def default(self, o):
        serial = {}
        for name in dir(o):
            value = getattr(o, name)
            datatype = type(value)
            if datatype is datetime:
                serial[name] = value.isoformat(timespec='milliseconds')
            elif datatype is Decimal:
                serial[name] = round(float(value), 3)
            elif datatype is int:
                serial[name] = value
            elif datatype is str:
                serial[name] = value
            elif isinstance(value, BaseItem):
                serial[name] = self.default(value)
            elif value:
                try:
                    serial[name] = json.JSONEncoder.default(self, value)
                except TypeError as e:
                    logger.error("No serialize property %s with value %s" % (name, value,))

        return serial
