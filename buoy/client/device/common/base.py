# -*- coding: utf-8 -*-

import logging
from queue import Queue, Empty, Full
from threading import Thread
from typing import List

import paho.mqtt.client as mqtt
import time
from serial import Serial, SerialException

from buoy.client.device.common.database import DeviceDB
from buoy.client.device.common.exceptions import LostConnectionException, DeviceNoDetectedException, \
    ProcessDataExecption
from buoy.client.internet_connection import is_connected_to_internet
from buoy.client.notification.common import BaseItem

logger = logging.getLogger(__name__)


class BaseThread(Thread):
    def __init__(self, queue_notice: Queue, **kwargs):
        self.timeout_wait = kwargs.pop('timeout_wait', 0.2)
        super(BaseThread, self).__init__(**kwargs)
        self.active = False
        self.queue_notice = queue_notice

    def run(self):
        self.active = True
        while self.is_active():
            self.activity()
            time.sleep(self.timeout_wait)

    def is_active(self) -> bool:
        """
        Retorna el estado del hilo, activo o parado

        :return: Estado del hilo
        """
        return self.active

    def activity(self):
        """
        Función donde implementar el proceso a ejecutar el hilo
        :return:
        """
        pass

    def stop(self):
        """ Para el hilo """
        self.active = False
        logging.info("Stop thread %s", self.__class__.__name__)

    def error(self, exception):
        self.queue_notice.put_nowait(exception)
        self.stop()


class DeviceBaseThread(BaseThread):
    def __init__(self, device: Serial, queue_notice: Queue, **kwargs):
        super(DeviceBaseThread, self).__init__(queue_notice)
        self.device = device

    def is_active(self):
        return super().is_active() and self.device.is_open


class DeviceReader(DeviceBaseThread):
    """ Clase encargada de leer y parsear los datos que devuelve el dispositivo """

    def __init__(self, device: Serial, queue_save_data: Queue, queue_notice: Queue, **kwargs):
        self.char_splitter = kwargs.pop('char_splitter', '\n')
        super(DeviceReader, self).__init__(device, queue_notice)
        self.first_item = False
        self.queue_save_data = queue_save_data
        self.buffer = ''

    def activity(self):
        try:
            self.read_data()
            logger.debug("Waiting data")
            if not self.is_buffer_empty():
                self.process_data()

        except (OSError, Exception) as ex:
            logger.error("Device disconnected")
            self.error(LostConnectionException(exception=ex))

    def read_data(self):
        self.buffer += self.device.read(self.device.in_waiting).decode()

    def is_buffer_empty(self):
        return self.char_splitter not in self.buffer

    def process_data(self):
        logger.debug("Proccessing data: %s", self.buffer)
        buffer = self.buffer.rsplit(self.char_splitter, 1)
        try:
            self.buffer = buffer[1].strip()
        except IndexError as ex:
            raise ProcessDataExecption(message="Proccesing data without char split", exception=ex)
        for line in self.split_by_lines(buffer[0]):
            item = self.parser(line)
            if item:
                self.queue_save_data.put_nowait(item)
                logger.info("Received line with data - " + line)
            logger.debug("Received data - " + line)

    def split_by_lines(self, buffer: str) -> List[str]:
        lines = buffer.split(self.char_splitter)
        return [l.strip() for l in lines if len(l.strip())]

    def parser(self, data) -> BaseItem:
        pass


class DeviceWriter(DeviceBaseThread):
    """ Clase encargada de enviar datos al dispositivo """

    def __init__(self, device: Serial, queue_write_data: Queue, queue_notice: Queue):
        super(DeviceWriter, self).__init__(device, queue_notice)
        self.queue_write_data = queue_write_data

    def activity(self):
        try:
            data = self.queue_write_data.get(timeout=self.timeout_wait)
            self.device.write(data.encode())
            logger.info("Send - " + data)
            self.queue_write_data.task_done()
        except SerialException as ex:
            logger.error("Device disconnected")
            self.error(LostConnectionException(exception=ex))
        except Empty:
            pass


class ItemSaveThread(BaseThread):
    """
    Clase encargada de guardar los datos en la base de datos
    """

    def __init__(self, db: DeviceDB, queue_save_data: Queue, queue_send_data: Queue, queue_notice: Queue):
        super(ItemSaveThread, self).__init__(queue_notice)
        self.db = db
        self.queue_save_data = queue_save_data
        self.queue_send_data = queue_send_data

    def activity(self):
        try:
            item = self.queue_save_data.get(timeout=self.timeout_wait)
            item = self.save(item)

            if item and not self.queue_send_data.full():
                try:
                    self.queue_send_data.put_nowait(item)
                except Full:
                    logger.warning("Data queue is full")

            self.queue_save_data.task_done()

        except Empty:
            pass

    def save(self, item):
        """ Guarda el registro en la base de datos """
        return self.db.save(item)


def loop(client):
    client.loop_start()


class ItemSendThread(BaseThread):
    """
    Clase base encargada de enviar los datos al servidor
    """

    def __init__(self, db: DeviceDB, queue_send_data: Queue, queue_notice: Queue, **kwargs):
        super(ItemSendThread, self).__init__(queue_notice)

        self.db = db
        self.queue_send_data = queue_send_data
        self.queue_notice = queue_notice
        self.connected_to_mqtt = False
        self.connected_to_internet = False
        self.thread_mqtt = None
        self.attemp_connect = False

        self.client_id = kwargs.pop("client_id", "")
        self.clean_session = kwargs.pop("clean_session", True)
        self.protocol = mqtt.MQTTv311
        self.transport = kwargs.pop("transport", "tcp")

        self.broker_url = kwargs.pop("broker_url", "iot.eclipse.org")
        self.broker_port = kwargs.pop("broker_port", 1883)
        self.topic_data = kwargs.pop("topic_data", "buoy")
        self.keepalive = kwargs.pop("keepalive", 60)

        self.client = mqtt.Client(client_id=self.client_id, protocol=self.protocol, clean_session=self.clean_session)
        if "username" in kwargs:
            self.username = kwargs.pop("username", "username")
            self.password = kwargs.pop("password", None)
            self.client.username_pw_set(self.username, self.password)

        self.qos = kwargs.pop("qos", 0)
        self.item_in_queue = set()

    def activity(self):
        if self.connected_to_mqtt:
            items = self.waiting_data()
            for item in items:
                if self.connected_to_mqtt:
                    self.add_item_in_queue(item)
                    self.send(item)
        elif is_connected_to_internet(max_attempts=1, time_between_attempts=1):
            logger.info("Connected to internet")
            try:
                if not self.attemp_connect:
                    self.attemp_connect = True
                    self.client.connect(host=self.broker_url, port=self.broker_port, keepalive=self.keepalive)
                    self.client.on_connect = self.on_connect
                    self.client.on_disconnect = self.on_disconnect
                    self.thread_mqtt = Thread(target=loop, args=(self.client,))
                    self.thread_mqtt.start()
            except Exception as ex:
                logger.error(ex, exc_info=True)
                logger.warning("Trying connect to broker, but there isn't internet connection")
                pass

    def waiting_data(self) -> List[BaseItem]:
        """
        Espera por los datos, los datos que envía el dispositivo tienen
        preferencia a los de la base de datos.

        :return Retorna una lista de datos
        :rtype Lista de tipo BaseItem
        """
        items = None
        while self.is_active() and (not items or not len(items)):
            try:
                item = self.queue_send_data.get_nowait()
                items = [item]
                self.queue_send_data.task_done()
            except Empty:
                items = self.db.get_items_to_send(discard=list(self.item_in_queue))
            time.sleep(self.timeout_wait)

        return items

    def add_item_in_queue(self, item: BaseItem):
        self.item_in_queue.add(item.id)

    def remove_item_the_queue(self, item: BaseItem):
        self.item_in_queue.discard(item.id)

    def send(self, item):
        logger.info("Publish datagi '%s' to topic '%s'" % (self.topic_data, str(item.to_json())))
        try:
            result = self.client.publish(self.topic_data, str(item.to_json()), qos=self.qos)
            result.wait_for_publish()
        except Exception as ex:
            logger.error(ex, exc_info=True)
            pass

        self.remove_item_the_queue(item)
        if result and result.rc == 0:
            logger.debug("Update item in db %i", item.id)
            self.db.set_sent(item.id)
        else:
            logger.warning("Error sended item %i", item.id)
            self.db.set_failed(item.id)

    def on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            logger.info("Connected to broker %s with client_id %s", self.broker_url, client)
            self.connected_to_mqtt = True
            if flags["session present"]:
                logger.info("Connected to broker using existing session")
            else:
                logger.info("Connected to broker using clean session")
        else:
            self.connected_to_mqtt = False
            if rc == 1:
                logger.error("Connection refused - incorrect protocol version")
            elif rc == 2:
                logger.error("Connection refused - invalid client identifier")
            elif rc == 3:
                logger.error("Connection refused - server unavailable")
            elif rc == 4:
                logger.error("Connection refused - bad username or password")
            elif rc == 5:
                logger.error("Connection refused - not authorised")
            else:
                logger.error("Error connected to broker")

    def on_disconnect(self, client, userdata, rc):
        self.connected_to_mqtt = False
        if rc != 0:
            logger.error("Unexpected disconnection to broker")
        else:
            client.loop_stop()
            super().stop()
        logger.info("Disconnected to broker with result code %s" % str(rc))

    def stop(self):
        logger.info("Disconnecting to broker")
        self.client.disconnect()


class Device(object):
    def __init__(self, *args, **kwargs):
        self.serial_config = kwargs.pop('serial_config', None)
        self.db = kwargs.pop('db')

        self.cls_reader = kwargs.pop('cls_reader', None)
        self.cls_writer = kwargs.pop('cls_writer', None)
        self.cls_save = kwargs.pop('cls_save', ItemSaveThread)
        self.cls_send = kwargs.pop('cls_send', ItemSendThread)
        self.mqtt = kwargs.pop('mqtt', None)

        self.qsize_send_data = kwargs.pop('qsize_send_data', 1000)

        self.queues = {}
        self._create_queues()

        # Device
        self.name = kwargs.pop('device_name')
        self._dev_connection = None

    def _create_queues(self):
        for queue_name in ['notice', 'write_data', 'save_data', 'send_data']:
            qsize = 0
            if queue_name == 'send_data':
                qsize = self.qsize_send_data
            self.queues[queue_name] = Queue(maxsize=qsize)

    def run(self):
        try:
            self.connect()
            self._create_threads()
            self._start_threads()
            self.configure()
            self._listener_exceptions()
        except Exception as ex:
            raise ex

    def connect(self):
        logger.info("Connecting to device")
        try:
            self._dev_connection = Serial(**self.serial_config)
        except SerialException as ex:
            raise DeviceNoDetectedException(process=self.name, exception=ex)
        logger.info("Connected to device")

    def _create_threads(self):
        if self.cls_writer:
            self._thread_writer = self.cls_writer(device=self._dev_connection,
                                                  queue_write_data=self.queues['write_data'],
                                                  queue_notice=self.queues['notice'])
        if self.cls_reader:
            self._thread_reader = self.cls_reader(device=self._dev_connection,
                                                  queue_save_data=self.queues['save_data'],
                                                  queue_notice=self.queues['notice'])
        if self.cls_save:
            self._thread_save = self.cls_save(queue_save_data=self.queues['save_data'],
                                              queue_send_data=self.queues['send_data'],
                                              queue_notice=self.queues['notice'],
                                              db=self.db)
        if self.cls_send:
            self._thread_send = self.cls_send(queue_send_data=self.queues['send_data'],
                                              queue_notice=self.queues['notice'],
                                              db=self.db, **self.mqtt)

    def _start_threads(self):
        self._run_action_threads(action='start')

    def _run_action_threads(self, action='start'):
        prefix = '_thread_'
        names = ['reader', 'writer', 'save', 'send']

        for name in names:
            field = prefix + name
            if hasattr(self, field):
                thread = getattr(self, field)
                getattr(thread, action)()

    def configure(self):
        pass

    def _listener_exceptions(self):
        while self.is_open():
            try:
                ex = self.queues['notice'].get(timeout=0.2)
                raise ex
            except Empty:
                pass

    def disconnect(self):
        logger.info("Disconnecting to device")
        self._stop_threads()
        if self.is_open():
            self._dev_connection.close()
        logger.info("Disconnected to device")

    def _stop_threads(self):
        self._run_action_threads(action='stop')

    def is_open(self):
        return self._dev_connection and self._dev_connection.is_open and self.is_active()

    def write(self, data):
        self.queues['write_data'].put_nowait(data + "\r")
