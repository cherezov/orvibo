#!/usr/bin/python3

# @file orvibo.py
# @author cherezov.pavel@gmail.com

# Change log:
#   1.0 Initial stable version
#   1.1 Mac and type arguments introduced for fast control known devices
#   1.2 Python3 discover bug fixed
#   1.3 ip argument is now optional in case of mac and type are passed
#   1.4 keep connection functionality implemented
#   1.4.1 Learn/Emit logging improved
#   1.5 Learn/Emit Orvibo SmartSwitch RF433 MHz signal support added
__version__ = "1.5"

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

LEARN_IR = b'\x6c\x73'
LEARN_IR_RESP = LEARN_IR

BLAST_IR = b'\x69\x63'

BLAST_RF433 = CONTROL
LEARN_RF433 = CONTROL

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

def _random_n_bytes(n):
    res = b''
    for n in range(n):
        res += _random_byte()
    return res

def _packet_id():
    return _random_n_bytes(2)

_placeholders = ['MAGIC', 'SPACES_6', 'ZEROS_4', 'CONTROL', 'CONTROL_RESP', 'SUBSCRIBE', 'LEARN_IR', 'BLAST_RF433', 'BLAST_IR', 'DISCOVER', 'DISCOVER_RESP' ]
def _debug_data(data):
    data = binascii.hexlify(bytearray(data))
    for s in _placeholders:
        p = binascii.hexlify(bytearray( globals()[s]))
        data = data.replace(p, b" + " + s.encode() + b" + ")
    return data[3:]

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
        return 'Packet {} {}: {}'.format('to' if self.type == self.Request else 'from', self.ip, _debug_data(self.data))

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

    @staticmethod
    def recv_all(sock, expectResponseType = None, timeout = 10):
       res = None
       while True:
           resp = Packet.recv(sock, expectResponseType, timeout)
           if resp is None:
                break
           res = resp
       return res

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
        response = subscr_packet.recv_all(s, SUBSCRIBE_RESP)

        self.__last_subscr_time = time.time()
        return response.data[-1] if response is not None else None

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

    def learn_rf433(self, fname = None):
        """ Learn Orvibo SmartSwitch RF433 signal.
        """
        # It is actually the same packet as for RF433 signal emit.
        key = _random_n_bytes(7)
        
        if fname is not None:
            with open(fname, 'wb') as f:
                f.write(key)

        self._learn_emit_rf433(1, key)
        return key

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

            learn_packet = Packet(self.ip).compile(LEARN_IR, self.mac, SPACES_6, b'\x01\x00', ZEROS_4)
            learn_packet.send(s)
            if learn_packet.recv(s, LEARN_IR_RESP) is None:
                self.__logger.warn('Failed to enter to Learning IR/RF433 mode')
                return

            self.__logger.info('Waiting {} sec for IR/RF433 signal...'.format(timeout))


            # LEARN_IR responses with such length will be skipped
            EMPTY_LEARN_IR = b'\x00\x18'

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

                if packet_with_signal.length == EMPTY_LEARN_IR:
                    self.__logger.debug('Skipped:\nEmpty packet = {}'.format(_debug_data(packet_with_signal.data)))
                    continue

                if packet_with_signal.cmd == LEARN_IR:
                    self.__logger.debug('SUCCESS:\n{}'.format(_debug_data(packet_with_signal.data)))
                    break

                self.__logger.debug('Skipped:\nUnexpected packet = {}'.format(_debug_data(packet_with_signal.data)))

            signal_split = packet_with_signal.data.split(self.mac + SPACES_6, 1)
            signal = signal_split[1][6:]

            if fname is not None:
                with open(fname, 'wb') as f:
                    f.write(signal)
                self.__logger.info('IR/RF433 signal got successfuly and saved to "{}" file'.format(fname))
            else:
                self.__logger.info('IR/RF433 signal got successfuly')

            return signal

    def _learn_emit_rf433(self, on, key):
        """ Learn/emit SmartSwitch RF433 signal.
        """
        with _orvibo_socket(self.__socket) as s:
                                                                                     # this also comes with 64 62 packet
            signal_packet = Packet(self.ip).compile(BLAST_RF433, self.mac, SPACES_6, key[:4],\
                        _packet_id(), b'\x01' if on else b'\x00', b'\x29\x00', key[4:])
            signal_packet.send(s)
            signal_packet.recv_all(s)
            self.__logger.debug('{}'.format(signal_packet))

    def emit_rf433(self, on, fname):
        """ Emit RF433 signal for Orvibo SmartSwitch only.
        """
        key = b''
        with open(fname, 'rb') as f:
            key = f.read()

        self._learn_emit_rf433(on, key)


    def emit_ir(self, signal):
        """ Emit IR signal

        Arguments:
        signal -- raw signal got with learn method or file name with ir signal to emit

        returns -- True if emit successs, otherwise False
        """

        with _orvibo_socket(self.__socket) as s:
            if self.__subscribe(s) is None:
                self.__logger.warn('Subscription failed while emiting IR signal')
                return False

            if self.type != Orvibo.TYPE_IRDA:
                self.__logger.warn('Attempt to emit IR signal for device with type {}'.format(self.type))
                return False

            if isinstance(signal, str):
                # Read IR code from file
                self.__logger.debug('Reading IR signal from file "{}"'.format(signal))
                with open(signal, 'rb') as f:
                    signal = f.read()

            signal_packet = Packet(self.ip).compile(BLAST_IR, self.mac, SPACES_6, b'\x65\x00\x00\x00', _packet_id(), signal)
            signal_packet.send(s)
            signal_packet.recv_all(s)
            self.__logger.info('IR signal emit successfuly')
            return True

def usage():
   print('orvibo.py [-v] [-L <log level>] [-i <ip>] [-m <mac> -x <irda|socket>] [-s <on/off>] [-e <file.ir>] [-t <file.ir>] [-r]')
   print('-i <ip>    - ip address of the Orvibo device, e.g 192.168.1.10')
   print('-m <mac>   - mac address string, e.g acdf4377dfcc')
   print('             Not valid without -i and -x options')
   print('-x <type>  - type of the Orvibo device: socket, irda')
   print('             Not valid without -i and -m options')
   print('-s <value> - switch on/off Orvibo Smart Socket: on, off')
   print('             Not valid without -i option and device types other than socket')
   print('-t <fname> - turns Orvibo AllOne into learning mode for 15 seconds or until catching IR signal')
   print('             Signal will be saved in "fname" file')
   print('             Not valid without -i option and device types other than "irda"')
   print('-e <fname> - emits IR signal stored in "fname" file')
   print('             Not valid without -i option or device types other than "irda"')
   print('-r         - tells module to teach/emit RF433 signal for Orvibo SmartSwitch')
   print('             Not valid without -i option or device types other than "irda"')
   print('-v         - prints module version')
   print('-L <level> - extended output information: debug, info, warn')
   print()
   print('Examples:')
   print('Discover all Orvibo devices on the network:')
   print('> orvibo.py')
   print('Discover all Orvibo device by ip:')
   print('> orvibo.py -i 192.168.1.10')
   print('Discover all Orvibo known device. Much faster than previous one:')
   print('> orvibo.py -i 192.168.1.10 -m acdf4377dfcc -x socket')
   print('Switch socket on:')
   print('> orvibo.py -i 192.168.1.10 -m acdf4377dfcc -x socket -s on')
   print('Grab IR signal:')
   print('> orvibo.py -i 192.168.1.20 -m bdea54883ade -x irda -t signal.ir')
   print('Emit IR signal:')
   print('> orvibo.py -i 192.168.1.20 -m bdea54883ade -x irda -e signal.ir')
   print('Grab SmartSwitch RF signal:')
   print('> orvibo.py -i 192.168.1.20 -m bdea54883ade -x irda -t smartswitch.rf -r')
   print('Emit SmartSwitch RF signal:')
   print('> orvibo.py -i 192.168.1.20 -m bdea54883ade -x irda -e signal.ir -r -s on')

if __name__ == '__main__':
   import sys
   import getopt

   class Opts:
      def __init__(self):
         self.help = False
         self.version = False
         self.log_level = logging.WARN
         self.ip = None
         self.mac = None
         self.otype = None
         self.switch = None
         self.emitFile = None
         self.teachFile = None
         self.rf = False

      def init(self):
         try:
            opts, args = getopt.getopt(sys.argv[1:], "rhvL:i:x:m:s:e:t:", ['loglevel=','ip=','mac=','type','socket=','emit=','teach=','zeach='])
         except getopt.GetoptError:
            return False

         for opt, arg in opts:
            if opt == ('-h', '--help'):
               self.help = True
            elif opt in ('-v', '--version'):
               self.version = True
            elif opt in ('-L', '--loglevel'):
               if arg.lower() == 'debug':
                   self.log_level = logging.DEBUG
               elif arg.lower() == 'info':
                   self.log_level = logging.INFO
               elif arg.lower() == 'warn':
                   self.log_level = logging.WARN
            elif opt in ('-i', '--ip'):
               self.ip = arg
            elif opt in ('-x', '--type'):
               self.otype = arg
            elif opt in ('-m', '--mac'):
               self.mac = arg
            elif opt in ('-s', '--socket'):
               self.switch = True if arg.lower() == 'on' or arg == '1' else False
            elif opt in ('-e', '--emit'):
               self.emitFile = arg
            elif opt in ('-t', '--teach'):
               self.teachFile = arg
            elif opt in ("-r", "--rf"):
               self.rf = True
         return True

      def discover_all(self):
         return self.ip is None and self.mac is None and self.switch is None and self.emitFile is None and self.teachFile is None

      def ip_skipped(self):
         return self.ip is None and self.mac is not None and self.otype is not None

      def teach_rf(self):
         return self.teachFile is not None and self.rf

      def emit_rf(self):
         return self.emitFile is not None and self.rf and self.switch is not None

      def emit_ir(self):
         return self.emitFile is not None and not self.rf

      def teach_ir(self):
         return self.teachFile is not None and not self.rf

   o = Opts()
   if not o.init():
      usage()
      sys.exit(2)

   if o.help:
      usage()
      sys.exit()

   if o.version:
      print(__version__)
      sys.exit()
      sys.exit(0)

   logging.basicConfig(level=o.log_level)

   if o.discover_all():
      for d in Orvibo.discover().values():
         d = Orvibo(*d)
         print(d)
      sys.exit(0)

   if o.ip_skipped():
      d = Orvibo(BROADCAST, o.mac, o.otype)
   elif o.mac is None:
      try:
         d = Orvibo.discover(o.ip)
      except OrviboException as e:
         print(e)
         sys.exit(-1)
   else:
      d = Orvibo(o.ip, o.mac, o.otype)

   print(d)

   if d.type == Orvibo.TYPE_SOCKET:
      if o.switch is None:
         print('Is enabled: {}'.format(d.on))
      else:
         if d.on != o.switch:
            d.on = o.switch
            print('Is enabled: {}'.format(d.on))
         else:
            print('Already {}.'.format('enabled' if o.switch else 'disabled'))
   elif d.type == Orvibo.TYPE_IRDA:
      if o.emit_rf():
         # It is required to wake up AllOne
         d.emit_ir(b' ')
         d.emit_rf433(o.switch, o.emitFile)
         print('Emit RF done.')
      elif o.emit_ir():
         d.emit_ir(o.emitFile)
         print('Emit IR done.')
      elif o.teach_rf():
         # It is required to wake up AllOne
         d.emit_ir(b' ')
         signal = d.learn_rf433(o.teachFile)
         print('Teach RF done.')
      elif o.teach_ir():
         signal = d.learn(o.teachFile)
         print('Teach IR done')
