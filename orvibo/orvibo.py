# @file orvibo.py
# @author cherezov.pavel@gmail.com

import logging
import struct
import select
import random
import socket
import binascii

PORT = 10000

TYPE_SOCKET = 'socket'
TYPE_IRDA = 'irda'

MAGIC = b'\x68\x64'
SPACES_6 = b'\x20\x20\x20\x20\x20\x20'
ZEROS_4 = b'\x00\x00\x00\x00'

ON = b'\x01'
OFF = b'\x00'

# CMD CODES
DISCOVERY = b'\x71\x61'
DISCOVERY_RESP = DISCOVERY

SUBSCRIBE = b'\x63\x6c'
SUBSCRIBE_RESP = SUBSCRIBE

CONTROL = b'\x64\x63'
CONTROL_RESP = CONTROL

SOCKET_EVENT = b'\x73\x66' # something happend with socket TODO:

LEARN_IR = b'\x6c\x73'
# LEARN_IR_RESP

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

def _create_udp_socket():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    for opt in [socket.SO_BROADCAST, socket.SO_REUSEADDR,socket.SO_BROADCAST]:
        sock.setsockopt(socket.SOL_SOCKET, opt, 1)
    sock.bind(('', PORT))
    return sock

def _create_orvibo_packet(*args):
    """ Assemblies packet to send to orvibo device.

    *args -- number of bytes strings that will be concatenated, and prefixed with MAGIC heaer and packet length.
    """

    length = len(MAGIC) + 2 # len itself
    packet = b''
    for a in args:
        length += len(a)
        packet += a

    msg_len_2 = struct.pack('>h', length)
    packet = MAGIC + msg_len_2 + packet
    return packet
    
placeholders = ['MAGIC', 'SPACES_6', 'ZEROS_4', 'CONTROL', 'CONTROL_RESP', 'SUBSCRIBE', 'BLAST_IR', 'DISCOVERY', 'DISCOVERY_RESP']
def _debug_data(data):
    data = binascii.hexlify(bytearray(data))
    for s in placeholders:
        p = binascii.hexlify(bytearray( globals()[s]))
        data = data.replace(p, b" + " + s.encode() + b" + ")
    return data

def parse_discovery_response(response):
    """ Extracts MAC address and Type of the device from response.

    response -- dicover response, format:
                MAGIC + LENGTH + DISCOVERY_RESP + b'\x00' + MAC + SPACES_6 + REV_MAC + ... TYPE
    """
    logging.debug('Discovered:\n{}'.format(_debug_data(response)) )

    header_len = len(MAGIC + DISCOVERY_RESP) + 2 + 1  # 2 length bytes, and 0x00
    mac_len = 6
    spaces_len = len(SPACES_6)

    mac_start = header_len
    mac_end = mac_start + mac_len
    mac = response[mac_start:mac_end]

    rev_mac_start = mac_end + spaces_len 
    rev_mac_end = rev_mac_start + mac_len
    rev_mac = response[rev_mac_start:rev_mac_end]

    type = None
    if b'SOC' in response:
        type = TYPE_SOCKET
    elif b'IRD' in response:
        type = TYPE_IRDA

    return (type, mac, rev_mac)

def discover(ip = None, mac = None):
    """ Collects all/exact Orvibo device(s) in the local network

    ip -- [optional] ip of the discovering device, e.g '192.168.1.1'
    mac -- [optional] MAC address of the discovering device, e.g b'accf238d1d22'

    If parameters are omited returns list of Orvibo objects, otherwise returns Orvibo object or raises OrviboException.
    """ 
    broadcast = '255.255.255.255'
    devices = {}
    try:
        s = _create_udp_socket()
        discover_packet = _create_orvibo_packet(DISCOVERY)
        s.sendto(bytearray(discover_packet), (broadcast, PORT))

        while True:
            r, w, x = select.select([s], [], [], 1)
            if s not in r:
                break

            data, addr = s.recvfrom(1024)

            t, _mac, _rmac = parse_discovery_response(data)
            dev = Orvibo(addr[0], _mac, t, _rmac)
            devices[dev.ip] = dev
    finally:
        s.close()


    matched = None
    if ip is not None: 
        if ip not in devices:
            raise OrviboException('Device ip={} not found.'.format(ip))
        # ip is set and found
        matched = devices[ip]
        devices = { ip : matched }

    if mac is not None:
        if mac not in [d.mac for d in devices.values()]:
            raise OrviboException('Device mac={} not found.'.format(mac))
        matched = [d for d in devices.values() if d.mac == mac][0]

    return matched if matched is not None else devices.values()

class Orvibo:
    """ Represents Orvibo device, such as wifi socket (TYPE_SOCKET) or AllOne IR blaster (TYPE_IRDA)
    """

    def __init__(self, host, mac = None, type = None, rev_mac = None):
        self.__logger = logging.getLogger('{}@{}'.format(self.__class__.__name__, host))
        self.ip = host
        self.mac = mac
        self.type = type
        self.rev_mac = rev_mac
        self.__socket = None

    def __repr__(self):
        mac = binascii.hexlify(bytearray(self.mac))
        return "Orvibo[type={}, ip={}, mac={}]".format(self.type, self.ip, mac)

    def __del__(self):
        self.close()

    def __enter__(self):
        return self

    def __exit__(self, type, value, traceback):
        self.close()

    def close(self):
        """ Close connection gracefuly.
        """
        if self.__socket is not None:
            self.__socket.close()

    def __discover(self):
        d = discover(self.ip)
        self.mac = d.mac
        self.type = d.type
        self.rev_mac = d.rev_mac

    def subscribe(self):
        if self.mac is None:
            self.__discover()

        if self.__socket is None:
            self.__socket = _create_udp_socket()

        subscr_packet = _create_orvibo_packet(SUBSCRIBE, self.mac, SPACES_6, self.rev_mac, SPACES_6)
        data = self.__send_recv_udp(subscr_packet, SUBSCRIBE_RESP)
        default_state = OFF
        return data[-1] if data else default_state

    @property
    def on(self):
        """ State property for TYPE_SOCKET

        :returns: State of device (on/off).
        """
        return self.subscribe()

    @on.setter
    def on(self, state):
        """ Change device state for TYPE_SOCKET

        :param state: True (on) or False (off).
        """
        self.__control_s20(ON if state else OFF)

    def __control_s20(self, state):
        if self.type != TYPE_SOCKET:
            return

        on_off_packet = _create_orvibo_packet(CONTROL, self.mac, SPACES_6, ZEROS_4, state)
        data = self.__send_recv_udp(on_off_packet, CONTROL_RESP)
        return data

    def __send_recv_udp(self, packet, expect = None):
        """
        """
        # Send
        r, w, x = select.select([], [self.__socket], [], 5)
        if self.__socket in w:
            self.__logger.debug('Sending: {}'.format(_debug_data(packet)) )
            self.__socket.sendto(bytearray(packet), (self.ip, PORT))

        # Receive
        data = b''
        for i in range(10):
            r, w, x = select.select([self.__socket], [], [self.__socket], 1)
            if self.__socket in r:
                data, addr = self.__socket.recvfrom(1024)

                if expect is not None and data[4:6] != expect:
                    continue
            elif self.__socket in x:
                raise OrviboException('Subscribe failed')
            else:
                # Nothing to read
                break

        self.__logger.debug('Received: {}'.format(_debug_data(data)) )
        return data

    def learn_ir(self, timeout = 15):
        self.subscribe()
        self.__enter_ir_learn_mode()
        return self.__wait_ir_code(timeout)

    def __enter_ir_learn_mode(self):
        if self.type != TYPE_IRDA:
            return

        learn_packet = _create_orvibo_packet(LEARN_IR, self.mac, SPACES_6, b'\x01\x00', ZEROS_4)
        ir_code = self.__send_recv_udp(learn_packet)
        return ir_code

    def __wait_ir_code(self, timeout=15):
        data = b''
        for i in range(timeout):
            r, w, x = select.select([self.__socket], [], [self.__socket], 1)
            if self.__socket in r:
                data, addr = self.__socket.recvfrom(1024)
                self.__logger.debug('waiting ir: {}'.format(_debug_data(data)) )
                break
            elif self.__socket in x:
                raise OrviboException('Socket failed')
            else: 
                self.__logger.debug('still waiting..')

        self.__logger.debug('data = : {}'.format(_debug_data(data)) )
        if not data:
            return b''

        d = data.split(self.mac + SPACES_6, 1)
        ir = d[1][6:]
        return ir


    def emit_ir(self, ir):
        if self.type != TYPE_IRDA:
            return

        ir_packet = _create_orvibo_packet(BLAST_IR, self.mac, SPACES_6, b'\x65\x00\x00\x00', _random_byte(), _random_byte(), ir)
        data = self.__send_recv_udp(ir_packet)
        return data

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
        for d in discover():
            print(d)
        sys.exit(0)

    if ip is not None:
        d = discover(ip)
        print(d)
        try:
            if d.type == TYPE_SOCKET:
                if switch is None:
                    print('Is enabled:', d.on)
                else:
                    d.on = switch
                    print('Is enabled:', d.on)
            elif d.type == TYPE_IRDA:
                if emitFile is not None:
                    d.subscribe()
                    with open(emitFile, 'rb') as f: 
                        ir = f.read()
                        d.emit_ir(ir)
                        print('Done.')
                elif teach is not None:
                    ir = d.learn_ir()

                    with open(teach, 'wb') as f: 
                        f.write(ir)
        except Exception as e:
            raise e
        finally:
            d.close()

        sys.exit(0)

