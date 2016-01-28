# @file orvibo.py
# @author cherezov.pavel@gmail.com

from contextlib import contextmanager
import logging
import struct
import select
import random
import socket
import binascii
import time

PORT = 10000

TYPE_SOCKET = 'socket'
TYPE_IRDA = 'irda'

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

SOCKET_EVENT = b'\x73\x66' # something happend with socket TODO:

LEARN_IR = b'\x6c\x73'
LEARN_IR_RESP = LEARN_IR

BLAST_IR = b'\x69\x63'
# BLAST_IR_RESP


class OrviboException(Exception):
    """ Module level exception class.
    """
    def __init__(self, msg):
        super().__init__(msg)

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

placeholders = ['MAGIC', 'SPACES_6', 'ZEROS_4', 'CONTROL', 'CONTROL_RESP', 'SUBSCRIBE', 'BLAST_IR', 'DISCOVER', 'DISCOVER_RESP']
def _debug_data(data):
    data = binascii.hexlify(bytearray(data))
    for s in placeholders:
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
        type = TYPE_SOCKET
    elif b'IRD' in response:
        type = TYPE_IRDA

    return (type, mac)

@contextmanager
def _orvibo_socket():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    for opt in [socket.SO_BROADCAST, socket.SO_REUSEADDR,socket.SO_BROADCAST]:
        sock.setsockopt(socket.SOL_SOCKET, opt, 1)
    sock.bind(('', PORT))

    yield sock

    sock.close()


class Packet:
    """ Represents response sender/recepient address and binary data.
    """

    Request = 'request'
    Response = 'response'

    def __init__(self, ip, data = None, type=Request):
        self.ip = ip 
        self.data = data

    def __repr__(self):
        return 'Packet {} {}: {}'.format('to' if self.type == Request else 'from', self.ip, _debug_data(self.packet))

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

    def __init__(self, ip, mac = None, type = 'Unknown'):
        self.ip = ip
        self.type = type
        self.mac = mac
        self.__last_subscr_time = time.time() - 1 # Orvibo doesn't like subscriptions frequently that 1 in 0.1sec
        self.__logger = logging.getLogger('{}@{}'.format(self.__class__.__name__, ip))
        
    def __repr__(self):
        mac = binascii.hexlify(bytearray(self.mac))
        return "Orvibo[type={}, ip={}, mac={}]".format(self.type, self.ip, mac)

    @staticmethod
    def discover(ip = None):
        broadcast = '255.255.255.255'
        devices = {}
        with _orvibo_socket() as s:
            logger = logging.getLogger(Orvibo.__class__.__name__)
            logger.debug('Discovering Orvibo devices')
            discover_packet = Packet(broadcast)
            discover_packet.compile(DISCOVER)
            discover_packet.send(s)
            
            for indx in range(512): # supposer there are less then 512 devices in the network
                p = discover_packet.recv(s)
                if p is None:
                    # No more packets in the socket
                    break

                orvibo_type, orvibo_mac = _parse_discover_response(p.data)

                if not orvibo_mac:
                    # Filter ghosts devices
                    continue

                devices[p.ip] = (p.ip, orvibo_mac, orvibo_type)

        if ip is None:
            return devices

        if ip not in devices.keys():
            raise OrviboException('Device ip={} not found.'.format(ip))

        return Orvibo(*devices[ip])

    def subscribe(self):
        if self.mac is None:
            self.__logger.debug('MAC address is not provided. Discovering..')
            d = Orvibo.discover(self.ip)
            self.mac = d.mac

        with _orvibo_socket() as s:
            return self.__subscribe(s)

    def __subscribe(self, s):
        if time.time() - self.__last_subscr_time < 0.1:
            time.sleep(0.1)

        subscr_packet = Packet(self.ip)
        subscr_packet.compile(SUBSCRIBE, self.mac, SPACES_6, _reverse_bytes(self.mac), SPACES_6)
        subscr_packet.send(s)
        response = subscr_packet.recv(s, SUBSCRIBE_RESP)
        default_state = OFF

        self.__last_subscr_time = time.time()
        return response.data[-1] if response else None

    def __control_s20(self, switchOn):
        with _orvibo_socket() as s:
            curr_state = self.__subscribe(s)

            if self.type != TYPE_SOCKET:
                self.__logger.warn('Attempt to control device with type {} as socket.'.format(self.type))
                return

            if curr_state is None:
                # something wrong with subscribing
                self.__logger.warn('Subscription failed while controlling wifi socket')
                return

            state = ON if switchOn else OFF
            if curr_state == state:
                # No need to switch on device that is already switched on
                self.__logger.warn('No need to switch {0} device which is already switched {0}'.format('on' if switchOn else 'off'))
                return

            self.__logger.debug('Socket is switching {}'.format('on' if switchOn else 'off'))
            on_off_packet = Packet(self.ip)
            on_off_packet.compile(CONTROL, self.mac, SPACES_6, ZEROS_4, state)
            on_off_packet.send(s)
            if on_off_packet.recv(s, CONTROL_RESP) is not None:
                self.__logger.info('Socket is switched {} successfuly.'.format('on' if switchOn else 'off'))
            else:
                self.__logger.warn('Socket switching {} failed.'.format('on' if switchOn else 'off'))

    @property
    def on(self):
        """ State property for TYPE_SOCKET

        :returns: State of device (on/off).
        """
        return self.subscribe() == 1

    @on.setter
    def on(self, state):
        """ Change device state for TYPE_SOCKET

        :param state: True (on) or False (off).
        """
        self.__control_s20(state)

    def learn_ir(self, fname = None, timeout = 15):
        with _orvibo_socket() as s:
            if self.__subscribe(s) is None:
                self.__logger.warn('Subscription failed while entering to Learning IR mode')
                return

            if self.type != TYPE_IRDA:
                self.__logger.warn('Attempt to enter to Learning IR mode for device with type {}'.format(self.type))
                return
            
            self.__logger.debug('Entering to Learning IR mode')

            learn_packet = Packet(self.ip).compile(LEARN_IR, self.mac, SPACES_6, b'\x01\x00', ZEROS_4)
            learn_packet.send(s)
            if learn_packet.recv(s, LEARN_IR_RESP) is None:
                self.__logger.warn('Failed to enter to Learning IR mode')
                return

            self.__logger.info('Waiting for IR signal...')
            packet_with_ir = learn_packet.recv(s, timeout=timeout)
            if packet_with_ir.data is None or len(packet_with_ir.data) == 0:
                self.__logger.warn('Nothing happend during {} sec'.format(timeout))
                return

            print(_debug_data(packet_with_ir.data)) 
            ir_split = packet_with_ir.data.split(self.mac + SPACES_6, 1)
            ir = ir_split[1][6:]

            if fname is not None:
                with open(fname, 'wb') as f: 
                    f.write(ir)
                self.__logger.info('IR signal got successfuly and saved to "{}" file'.format(fname))
            else:
                self.__logger.info('IR signal got successfuly')

            return ir

    def emit_ir(self, ir):
        with _orvibo_socket() as s:
            if self.__subscribe(s) is None:
                self.__logger.warn('Subscription failed while emiting IR signal')
                return

            if self.type != TYPE_IRDA:
                self.__logger.warn('Attempt to emit IR signal for device with type {}'.format(self.type))
                return

            if isinstance(ir, str):
                # Read IR code from file
                self.__logger.debug('Reading IR signal from file "{}"'.format(ir))
                with open(ir, 'rb') as f:
                    ir = f.read()

            ir_packet = Packet(self.ip).compile(BLAST_IR, self.mac, SPACES_6, b'\x65\x00\x00\x00', _random_byte(), _random_byte(), ir)
            ir_packet.send(s)
            ir_packet.recv(s)
            self.__logger.info('IR signal emit successfuly')
        
if __name__ == '__main__':

    import sys
    import getopt

    try:
        opts, args = getopt.getopt(sys.argv[1:], "hL:i:s:e:t:", ['loglevel=','ip=','switch=','emit=','teach='])
    except getopt.GetoptError:
        print('orvibo.py -L <log level> -i <ip> -s <on/off> -e <file.ir> -t <file.ir>')
        sys.exit(2)

    loglevel = logging.WARN
    ip = None
    switch = None
    emitFile = None
    teach = None

    for opt, arg in opts:
        if opt == '-h':
            print('orvibo.py -L <log level> -i <ip> -s <on/off> -e <file.ir> -t <file.ir>')
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
        elif opt in ("-s", "--switch"):
            switch = True if arg.lower() == 'on' or arg == '1' else False
        elif opt in ("-e", "--emit"):
            emitFile = arg
        elif opt in ("-t", "--teach"):
            teach = arg


    logging.basicConfig(level=loglevel)

    if ip is None and switch is None and emitFile is None and teach is None:
        for d in Orvibo.discover().values():
            d = Orvibo(*d)
            print(d)
        sys.exit(0)

    if ip is not None:
        d = Orvibo.discover(ip)
        print(d)

        if d.type == TYPE_SOCKET:
            if switch is None:
                print('Is enabled:', d.on)
            else:
                if d.on != switch:
                    d.on = switch
                    print('Is enabled:', d.on)
                else:
                    print('Already enabled.')
        elif d.type == TYPE_IRDA:
            if emitFile is not None:
                d.emit_ir(emitFile)
                print('Done.')
            elif teach is not None:
                ir = d.learn_ir(teach)

        sys.exit(0)

