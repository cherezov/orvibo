import logging
import struct
import select
import random
import socket
import binascii
import time


PORT = 10000

def reverse(mac):
    ba = bytearray(mac)
    ba.reverse()
    return bytes(ba)

def randomBit():
    return bytes([int(256 * random.random())])

MAGIC = b'\x68\x64'
SPACES_6 = b'\x20\x20\x20\x20\x20\x20'
ZEROS_4 = b'\x00\x00\x00\x00'
CONTROL = b'\x00\x17\x64\x63'
ON = b'\x01'
OFF = b'\x00'


SUBSCRIBE = b'\x63\x6c'

BLAST_IR = b'\x69\x63'

#DISCOVERY = b'\x00\x06\x71\x61' + ZEROS_4
DISCOVERY = b'\x71\x61'
DISCOVERY_RESP = b'\x00\x2a\x71\x61'

SOCK = b'\x53\x4f\x43\x30\x30'


lenght = b'\x01\xc2'
ir_len = b'\xa8\x01'


def createUdpSocket():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    for opt in [socket.SO_BROADCAST, socket.SO_REUSEADDR,socket.SO_BROADCAST]:
        sock.setsockopt(socket.SOL_SOCKET, opt, 1)
    sock.bind(('', PORT))
    return sock

def msg_len(n):
    return struct.pack('>h', n)

def createPacket(*args):
    length = len(MAGIC) + 2
    packet = b''
    for a in args:
        length += len(a)
        packet += a

    msg_len_2 = struct.pack('>h', length)
    packet = MAGIC + msg_len_2 + packet
    return packet


    
placeholders = ['MAGIC', 'SPACES_6', 'ZEROS_4', 'SUBSCRIBE', 'BLAST_IR', 'REV_MAC', 'lenght', 'ir_len', 'DISCOVERY', 'DISCOVERY_RESP', 'SOCK']
def parse_rcv(data):
    data = binascii.hexlify(bytearray(data))
    for s in placeholders:
        p = binascii.hexlify(bytearray( globals()[s]))
        data = data.replace(p, b" + " + s.encode() + b" + ")
    return data

def parse_discovery_response(data):
    # Response:
    # MAGIC + DISCOVERY_RESP + MAC + SPACES_6 + REV_MAC + ... TYPE
    header_len = len(MAGIC + DISCOVERY_RESP) 
    mac_len = 6
    spaces_len = len(SPACES_6)

    mac_start = header_len + 1
    mac_end = mac_start + mac_len
    mac = data[mac_start:mac_end]

    rev_mac_start = mac_end + spaces_len 
    rev_mac_end = rev_mac_start + mac_len
    rev_mac = data[rev_mac_start:rev_mac_end]

    type = None
    if b'SOC' in data:
        type = 'socket'
    elif b'IRD' in data:
        type = 'irda'

    #mac = binascii.hexlify(bytearray(mac))
    #rev_mac = binascii.hexlify(bytearray(rev_mac))
    return (type, mac, rev_mac)

def discover(ip=None):
    host = '255.255.255.255'
    try:
        s = createUdpSocket()
        discover_packet = createPacket(DISCOVERY)
        s.sendto(bytearray(discover_packet), (host, PORT))

        devices = []
        while True:
            r, w, x = select.select([s], [], [], 1)
            if s not in r:
                break

            data, addr = s.recvfrom(1024)

            if ip is not None and addr[0] != ip:
                continue

            t, mac, rmac = parse_discovery_response(data)
            if mac in [d.mac for d in devices]:
                continue

            dev = Orvibo(addr[0], mac, t, rmac)
            if ip is not None:
                return dev 

            devices.append(dev)
        return devices
    finally:
        s.close()

class Orvibo:
    def __init__(self, host, mac=None, type=None, rev_mac = None):
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

    def close(self):
        if self.__socket is not None:
            self.__socket.close()

    def discover(self):
        d = discover(self.ip)
        if d is None:
            raise Exception('No such device in the network.')
        self.mac = d.mac
        self.type = d.type
        self.rev_mac = d.rev_mac

    def interactUpd(self, packet):
        # Send
        r, w, x = select.select([], [self.__socket], [], 5)
        if self.__socket in w:
            self.__logger.debug('Sending: {}'.format(parse_rcv(packet)) )
            self.__socket.sendto(bytearray(packet), (self.ip, PORT))

        # Receive
        success = False
        data = b''
        for i in range(10):
            print('.',)
            r, w, x = select.select([self.__socket], [], [self.__socket], 1)
            if self.__socket in r:
                data, addr = self.__socket.recvfrom(1024)
                success = True
                break
            elif self.__socket in x:
                raise Exception('Subscribe failed')

        self.__logger.debug('Received: {}'.format(parse_rcv(data)) )
        return success, data

    def subscribe(self):
        if self.mac is None:
            self.discover()

        if self.__socket is not None:
            # already subscribed
            return

        self.__socket = createUdpSocket()

        subscr_packet = MAGIC + b'\x00\x1e' + SUBSCRIBE + self.mac + SPACES_6 + self.rev_mac + SPACES_6;
        success, data = self.interactUpd(subscr_packet)
        state = data[-1]
        return success, state

    def control_s20(self, state):
        #if self.type != 'socket':
        #    return

        on_off_packet = MAGIC + CONTROL + self.mac + SPACES_6 + ZEROS_4 + state
        success, data = self.interactUpd(on_off_packet)
        return success

    def wait_ir(self, timeout=15):
        data = b''
        for i in range(timeout):
            r, w, x = select.select([self.__socket], [], [self.__socket], 1)
            if self.__socket in r:
                data, addr = self.__socket.recvfrom(1024)
                self.__logger.debug('waiting ir: {}'.format(parse_rcv(data)) )
                break
            elif self.__socket in x:
                raise Exception('Subscribe failed')
            else: 
                self.__logger.debug('still waiting..')

        d = data.split(self.mac + SPACES_6, 1)
        self.__logger.debug('data0 = : {}'.format(parse_rcv(d[0])) )
        self.__logger.debug('data1 = : {}'.format(parse_rcv(d[1])) )

        ir = d[1][6:]
        self.__logger.debug('ir = : {}'.format(parse_rcv(ir)) )
        return ir

    def __enter__(self):
        pass

    def __exit__(self, type, value, traceback):
        self.close()

    def learn_ir(self):
        if self.type != 'irda':
            return

        learn_packet = MAGIC + b'\x00\x18' + b'\x6c\x73' + self.mac + SPACES_6 + b'\x01\x00' + ZEROS_4
        success, ir_code = self.interactUpd(learn_packet)
        return success, ir_code

    def push_ir(self, ir):
        if self.type != 'irda':
            return

        lenght = msg_len( len(MAGIC) + 2 + len(BLAST_IR) + len(self.mac) + len(SPACES_6) + 4 + 2 + len(ir) )
        #ir_packet = MAGIC + lenght + BLAST_IR + self.mac + SPACES_6 + b'\xd7\x70\x27\x12' + randomBit() + randomBit() + ir
        ir_packet = MAGIC + lenght + BLAST_IR + self.mac + SPACES_6 + b'\x65\x00\x00\x00' + randomBit() + randomBit() + ir
        success, data = self.interactUpd(ir_packet)
        return success, data

if __name__ == '__main__':

    logging.basicConfig(level=logging.DEBUG)

    try:
        for d in discover():
            print(d)
        

        #d = discover('192.168.1.37')

        #print(d)
        #print(d.subscribe())
        #print(d.control_s20(ON))
        #d.learn_ir()
        #print(d.subscribe())
        #print( d.interactUpd(payload) )
        #ir = d.wait_ir()

        #with open('tv_power.ir', 'wb') as f: 
        #    f.write(ir)

        #input()

        #with open('tv_power.ir', 'rb') as f: 
        #    ir = f.read()
        #    print(d.push_ir(ir))
        #    print('done')

    finally:
        d.close()

