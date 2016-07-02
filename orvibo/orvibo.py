#!/usr/bin/python3
# @file orvibo.py
# @author cherezov.pavel@gmail.com

# Change log:
#   1.0 Initial stable version
#   1.1 Mac and type arguments introduced for fast control known devices
#   1.2 Python3 discover bug fixed
#   1.3 ip argument is now optional in case of mac and type are passed
#   1.4 keep connection functionality implemented
__version__ = "1.4"

from contextlib import contextmanager
import logging
import struct
import select
import random
import socket
import binascii
import time
import sys

py3 = sys.version_info[0] == 3

BROADCAST = '255.255.255.255'
PORT = 10000

MAGIC = b'\x68\x64'
SPACES_6 = b'\x20\x20\x20\x20\x20\x20'
ZEROS_4 = b'\x00\x00\x00\x00'

ON = b'\x01'
OFF = b'\x00'

# CMD CODES
DISCOVER = b'\x71\x61'
DISCOVER_RESP = DISCOVER

SUBSCRIBE = b'\x63\x6c'
SUBSCRIBE_RESP = SUBSCRIBE

CONTROL = b'\x64\x63'
CONTROL_RESP = CONTROL

SOCKET_EVENT = b'\x73\x66' # something happend with socket

LEARN_IR_RF433 = b'\x6c\x73'
LEARN_IR_RF433_RESP = LEARN_IR_RF433

BLAST_IR_RF433 = b'\x69\x63'
# BLAST_IR_RF433_RESP


class OrviboException(Exception):
    """ Module level exception class.
    """
    def __init__(self, msg):
        super(OrviboException, self).__init__(msg)

def _reverse_bytes(mac):
    """ Helper method to reverse bytes order.

    mac -- bytes to reverse
    """
    ba = bytearray(mac)
    ba.reverse()
    return bytes(ba)

def _random_byte():
    """ Generates random single byte.
    """
    return bytes([int(256 * random.random())])

_placeholders = ['MAGIC', 'SPACES_6', 'ZEROS_4', 'CONTROL', 'CONTROL_RESP', 'SUBSCRIBE', 'BLAST_IR_RF433', 'DISCOVER', 'DISCOVER_RESP']
def _debug_data(data):
    data = binascii.hexlify(bytearray(data))
    for s in _placeholders:
        p = binascii.hexlify(bytearray( globals()[s]))
        data = data.replace(p, b" + " + s.encode() + b" + ")
    return data

def _parse_discover_response(response):
    """ Extracts MAC address and Type of the device from response.

    response -- dicover response, format:
                MAGIC + LENGTH + DISCOVER_RESP + b'\x00' + MAC + SPACES_6 + REV_MAC + ... TYPE
    """
    header_len = len(MAGIC + DISCOVER_RESP) + 2 + 1  # 2 length bytes, and 0x00
    mac_len = 6
    spaces_len = len(SPACES_6)

    mac_start = header_len
    mac_end = mac_start + mac_len
    mac = response[mac_start:mac_end]

    type = None
    if b'SOC' in response:
        type = Orvibo.TYPE_SOCKET

    elif b'IRD' in response:
        type = Orvibo.TYPE_IRDA

    return (type, mac)

def _create_orvibo_socket(ip=''):
    """ Creates socket to talk with Orvibo devices.

    Arguments:
    ip - ip address of the Orvibo device or empty string in case of broadcasting discover packet.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    for opt in [socket.SO_BROADCAST, socket.SO_REUSEADDR, socket.SO_BROADCAST]:
        sock.setsockopt(socket.SOL_SOCKET, opt, 1)
    if ip:
        sock.connect((ip, PORT))
    else:
        sock.bind((ip, PORT))
    return sock

@contextmanager
def _orvibo_socket(external_socket = None):
    sock = _create_orvibo_socket() if external_socket is None else external_socket

    yield sock

    if external_socket is None:
        sock.close()
    else:
        pass

class Packet:
    """ Represents response sender/recepient address and binary data.
    """

    Request = 'request'
    Response = 'response'

    def __init__(self, ip = BROADCAST, data = None, type = Request):
        self.ip = ip
        self.data = data
        self.type = type

    def __repr__(self):
        return 'Packet {} {}: {}'.format('to' if self.type == Request else 'from', self.ip, _debug_data(self.packet))

    @property
    def cmd(self):
        """ 2 bytes command of the orvibo packet
        """
        if self.data is None:
            return b''
        return self.data[4:6]

    @property
    def length(self):
        """ 2 bytes command of the orvibo packet
        """
        if self.data is None:
            return b''
        return self.data[2:4]


    def send(self, sock, timeout = 10):
        """ Sends binary packet via socket.

        Arguments:
        sock -- socket to send through
        packet -- byte string to send
        timeout -- number of seconds to wait for sending operation
        """
        if self.data is None:
            # Nothing to send
            return

        for i in range(timeout):
            r, w, x = select.select([], [sock], [sock], 1)
            if sock in w:
                sock.sendto(bytearray(self.data), (self.ip, PORT))
            elif sock in x:
                raise OrviboException("Failed while sending packet.")
            else:
                # nothing to send
                break

    @staticmethod
    def recv(sock, expectResponseType = None, timeout = 10):
        """ Receive first packet from socket of given type

        Arguments:
        sock -- socket to listen to
        expectResponseType -- 2 bytes packet command type to filter result data
        timeout -- number of seconds to wait for response
        """
        response = None
        for i in range(10):
            r, w, x = select.select([sock], [], [sock], 1)
            if sock in r:
                data, addr = sock.recvfrom(1024)

                if expectResponseType is not None and data[4:6] != expectResponseType:
                    continue

                response = Packet(addr[0], data, Packet.Response)
                break
            elif sock in x:
                raise OrviboException('Getting response failed')
            else:
                # Nothing to read
                break

        return response

    def compile(self, *args):
        """ Assemblies packet to send to orvibo device.

        *args -- number of bytes strings that will be concatenated, and prefixed with MAGIC heaer and packet length.
        """

        length = len(MAGIC) + 2 # len itself
        packet = b''
        for a in args:
            length += len(a)
            packet += a

        msg_len_2 = struct.pack('>h', length)
        self.data = MAGIC + msg_len_2 + packet
        return self

class Orvibo(object):
    """ Represents Orvibo device, such as wifi socket (TYPE_SOCKET) or AllOne IR blaster (TYPE_IRDA)
    """

    TYPE_SOCKET = 'socket'
    TYPE_IRDA = 'irda'

    def __init__(self, ip, mac = None, type = 'Unknown'):
        self.ip = ip
        self.type = type
        self.__last_subscr_time = time.time() - 1 # Orvibo doesn't like subscriptions frequently that 1 in 0.1sec
        self.__logger = logging.getLogger('{}@{}'.format(self.__class__.__name__, ip))
        self.__socket = None
        self.mac = mac

        # TODO: make this tricky code clear
        if py3 and isinstance(mac, str):
            self.mac = binascii.unhexlify(mac)
        else:
            try:
                self.mac = binascii.unhexlify(mac)
            except:
                pass

        if mac is None:
            self.__logger.debug('MAC address is not provided. Discovering..')
            d = Orvibo.discover(self.ip)
            self.mac = d.mac
            self.type = d.type

    def __del__(self):
        self.close()

    def close(self):
        if self.__socket is not None:
            try:
                self.__socket.close()
            except socket.error:
                # socket seems not alive
                pass
            self.__socket = None

    @property
    def keep_connection(self):
        """ Keeps connection to the Orvibo device.
        """
        return self.__socket is not None

    @keep_connection.setter
    def keep_connection(self, value):
        """ Keeps connection to the Orvibo device.
        """
        # Close connection if alive
        self.close()

        if value:
            self.__socket = _create_orvibo_socket(self.ip)
            if self.__subscribe(self.__socket) is None:
                raise OrviboException('Connection subscription error.')
        else:
            self.close()

    def __repr__(self):
        mac = binascii.hexlify(bytearray(self.mac))
        return "Orvibo[type={}, ip={}, mac={}]".format(self.type, 'Unknown' if self.ip == BROADCAST else self.ip, mac.decode('utf-8') if py3 else mac)

    @staticmethod
    def discover(ip = None):
        """ Discover all/exact devices in the local network

        Arguments:
        ip -- ip address of the discovered device

        returns -- map {ip : (ip, mac, type)} of all discovered devices if ip argument is None
                   Orvibo object that represents device at address ip.
        raises -- OrviboException if requested ip not found
        """
        devices = {}
        with _orvibo_socket() as s:
            logger = logging.getLogger(Orvibo.__class__.__name__)
            logger.debug('Discovering Orvibo devices')
            discover_packet = Packet(BROADCAST)
            discover_packet.compile(DISCOVER)
            discover_packet.send(s)

            for indx in range(512): # supposer there are less then 512 devices in the network
                p = discover_packet.recv(s)
                if p is None:
                    # No more packets in the socket
                    break

                orvibo_type, orvibo_mac = _parse_discover_response(p.data)
                logger.debug('Discovered values: type={}, mac={}'.format(orvibo_type, orvibo_mac));

                if not orvibo_mac:
                    # Filter ghosts devices
                    continue

                devices[p.ip] = (p.ip, orvibo_mac, orvibo_type)

        if ip is None:
            return devices

        if ip not in devices.keys():
            raise OrviboException('Device ip={} not found in {}.'.format(ip, devices.keys()))

        return Orvibo(*devices[ip])

    def subscribe(self):
        """ Subscribe to device.

        returns -- last response byte, which represents device state
        """
        with _orvibo_socket(self.__socket) as s:
            return self.__subscribe(s)

    def __subscribe(self, s):
        """ Required action after connection to device before sending any requests

        Arguments:
        s -- socket to use for subscribing

        returns -- last response byte, which represents device state
        """

        if time.time() - self.__last_subscr_time < 0.1:
            time.sleep(0.1)

        subscr_packet = Packet(self.ip)
        subscr_packet.compile(SUBSCRIBE, self.mac, SPACES_6, _reverse_bytes(self.mac), SPACES_6)
        subscr_packet.send(s)
        response = subscr_packet.recv(s, SUBSCRIBE_RESP)

        self.__last_subscr_time = time.time()
        return response.data[-1] if response else None

    def __control_s20(self, switchOn):
        """ Switch S20 wifi socket on/off

        Arguments:
        switchOn -- True to switch on socket, False to switch off

        returns -- True if switch success, otherwise False
        """

        with _orvibo_socket(self.__socket) as s:
            curr_state = self.__subscribe(s)

            if self.type != Orvibo.TYPE_SOCKET:
                self.__logger.warn('Attempt to control device with type {} as socket.'.format(self.type))
                return False

            if curr_state is None:
                self.__logger.warn('Subscription failed while controlling wifi socket')
                return False

            state = ON if switchOn else OFF
            if curr_state == state:
                self.__logger.warn('No need to switch {0} device which is already switched {0}'.format('on' if switchOn else 'off'))
                return False

            self.__logger.debug('Socket is switching {}'.format('on' if switchOn else 'off'))
            on_off_packet = Packet(self.ip)
            on_off_packet.compile(CONTROL, self.mac, SPACES_6, ZEROS_4, state)
            on_off_packet.send(s)
            if on_off_packet.recv(s, CONTROL_RESP) is None:
                self.__logger.warn('Socket switching {} failed.'.format('on' if switchOn else 'off'))
                return False

            self.__logger.info('Socket is switched {} successfuly.'.format('on' if switchOn else 'off'))
            return True

    @property
    def on(self):
        """ State property for TYPE_SOCKET

        Arguments:
        returns -- State of device (True for on/False for off).
        """

        onValue = 1 if py3 else ON
        return self.subscribe() == onValue

    @on.setter
    def on(self, state):
        """ Change device state for TYPE_SOCKET

        Arguments:
        state -- True (on) or False (off).

        returns -- nothing
        """
        self.__control_s20(state)

    def learn_ir(self, fname = None, timeout = 15):
        """ Backward compatibility
        """
        return self.learn(self, fname, timeout)

    def learn_rf433(self, fname = None, timeout = 15):
        """ Backward compatibility
        """
        return self.learn(self, fname, timeout)

    def learn(self, fname = None, timeout = 15):
        """ Read signal using your remote for future emit
            Supports IR and RF 433MHz remotes

        Arguments:
        fname -- [optional] file name to store IR/RF433 signal to
        timeout -- number of seconds to wait for IR/RF433 signal from remote

        returns -- byte string with IR/RD433 signal
        """

        with _orvibo_socket(self.__socket) as s:
            if self.__subscribe(s) is None:
                self.__logger.warn('Subscription failed while entering to Learning IR/RF433 mode')
                return

            if self.type != Orvibo.TYPE_IRDA:
                self.__logger.warn('Attempt to enter to Learning IR/RF433 mode for device with type {}'.format(self.type))
                return

            self.__logger.debug('Entering to Learning IR/RF433 mode')

            learn_packet = Packet(self.ip).compile(LEARN_IR_RF433, self.mac, SPACES_6, b'\x01\x00', ZEROS_4)
            learn_packet.send(s)
            if learn_packet.recv(s, LEARN_IR_RF433_RESP) is None:
                self.__logger.warn('Failed to enter to Learning IR/RF433 mode')
                return

            self.__logger.info('Waiting {} sec for IR/RF433 signal...'.format(timeout))


            # LEARN_IR_RF433 responses with such length will be skipped
            EMPTY_LEARN_IR_RF433 = b'\x00\x18'

            start_time = time.time()
            while True:
                elapsed_time = time.time() - start_time
                if elapsed_time > timeout:
                    self.__logger.warn('Nothing happend during {} sec'.format(timeout))
                    return

                packet_with_signal = learn_packet.recv(s, timeout=1)
                if packet_with_signal is None:
                    self.__logger.info('The rest time: {} sec'.format(int(timeout - elapsed_time)))
                    continue

                if packet_with_signal.length == EMPTY_LEARN_IR_RF433:
                    continue

                break

            signal_split = packet_with_signal.data.split(self.mac + SPACES_6, 1)
            signal = signal_split[1][6:]

            if fname is not None:
                with open(fname, 'wb') as f:
                    f.write(signal)
                self.__logger.info('IR/RF433 signal got successfuly and saved to "{}" file'.format(fname))
            else:
                self.__logger.info('IR/RF433 signal got successfuly')

            return signal

    def emit_ir(self, ir):
        """ Backward compatibility
        """
        return self.emit(ir)

    def emit_rf433(self, rf433):
        """ Backward compatibility
        """
        return self.emit(rf433)

    def emit(self, signal):
        """ Emit IR/RF433 signal

        Arguments:
        signal -- raw signal got with learn method or file name with ir/rf433 signal to emit

        returns -- True if emit successs, otherwise False
        """

        with _orvibo_socket(self.__socket) as s:
            if self.__subscribe(s) is None:
                self.__logger.warn('Subscription failed while emiting IR/RF433 signal')
                return False

            if self.type != Orvibo.TYPE_IRDA:
                self.__logger.warn('Attempt to emit IR/RF433 signal for device with type {}'.format(self.type))
                return False

            if isinstance(signal, str):
                # Read IR/RF433 code from file
                self.__logger.debug('Reading IR/RF433 signal from file "{}"'.format(signal))
                with open(signal, 'rb') as f:
                    signal = f.read()

            signal_packet = Packet(self.ip).compile(BLAST_IR_RF433, self.mac, SPACES_6, b'\x65\x00\x00\x00', _random_byte(), _random_byte(), signal)
            signal_packet.send(s)
            signal_packet.recv(s)
            self.__logger.info('IR/RF433 signal emit successfuly')
            return True

if __name__ == '__main__':

    import sys
    import getopt

    def usage():
        print('orvibo.py [-v] [-L <log level>] [-i <ip>] [-m <mac> -x <irda|socket>] [-s <on/off>] [-e <file.ir>] [-t <file.ir>]')

    try:
        opts, args = getopt.getopt(sys.argv[1:], "hvL:i:x:m:s:e:t:", ['loglevel=','ip=','mac=','type','switch=','emit=','teach='])
    except getopt.GetoptError:
        usage()
        sys.exit(2)

    loglevel = logging.WARN
    ip = None
    mac = None
    otype = None
    switch = None
    emitFile = None
    teach = None

    for opt, arg in opts:
        if opt == '-h':
            usage()
            sys.exit()
        if opt == '-v':
            print(__version__)
            sys.exit()
        elif opt in ("-L", "--loglevel"):
            if arg.lower() == 'debug':
                loglevel = logging.DEBUG
            elif arg.lower() == 'info':
                loglevel = logging.INFO
            elif arg.lower() == 'warn':
                loglevel = logging.WARN
        elif opt in ("-i", "--ip"):
            ip = arg
        elif opt in ("-x", "--type"):
            otype = arg
        elif opt in ("-m", "--mac"):
            mac = arg
        elif opt in ("-s", "--switch"):
            switch = True if arg.lower() == 'on' or arg == '1' else False
        elif opt in ("-e", "--emit"):
            emitFile = arg
        elif opt in ("-t", "--teach"):
            teach = arg

    logging.basicConfig(level=loglevel)

    if ip is None and mac is None and switch is None and emitFile is None and teach is None:
        # Nothing passed as parameter
        for d in Orvibo.discover().values():
            d = Orvibo(*d)
            print(d)
        sys.exit(0)

    if ip is None and mac is not None and otype is not None:
        # IP is skipped
        d = Orvibo(BROADCAST, mac, otype)
    elif ip is not None:
        if mac is None:
            try:
                d = Orvibo.discover(ip)
            except OrviboException as e:
                print(e)
                sys.exit(-1)
        else:
            d = Orvibo(ip, mac, otype)
    else:
        usage()
        sys.exit(1)

    print(d)

    if d.type == Orvibo.TYPE_SOCKET:
        if switch is None:
            print('Is enabled: {}'.format(d.on))
        else:
            if d.on != switch:
                d.on = switch
                print('Is enabled: {}'.format(d.on))
            else:
                print('Already {}.'.format('enabled' if switch else 'disabled'))
    elif d.type == Orvibo.TYPE_IRDA:
        if emitFile is not None:
            d.emit(emitFile)
            print('Done.')
        elif teach is not None:
            signal = d.learn(teach)
