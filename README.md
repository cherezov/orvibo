# orvibo
Module to manipulate Orvibo devices, such as s20 wifi sockets and AllOne IR blasters

## Refferences
* Module is based on [python-orvibo](https://github.com/happyleavesaoc/python-orvibo) module which currently supports Orvibo S20 sockets.
* Lots of info was found in [ninja-allone](https://github.com/Grayda/ninja-allone/blob/master/lib/allone.js) library
* S20 data analysis by anonymous is [here](http://pastebin.com/0w8N7AJD)

## TODO
* Test under linux platform
* Orvibo s20 event handler

## Issue
* ~After subscribtion to any Orvibo device, all devices becomes undiscoverable~

## Requires
* Python3

## Usage
### As console app
#### Discovering all Orvibo devices in the network
```shell
> python orvibo.py
Orvibo[type=socket, ip=192.168.1.45, mac=b'acdf238d1d2e']
Orvibo[type=irda, ip=192.168.1.37, mac=b'accf4378efdc']
```
#### Discover device by ip
```shell
> python orvibo.py -i 192.168.1.45
Orvibo[type=socket, ip=192.168.1.45, mac=b'acdf238d1d2e']
Is enabled: True
```
#### Switch s20 wifi socket
```shell
> python orvibo.py -i 192.168.1.45 -s on
Orvibo[type=socket, ip=192.168.1.45, mac=b'acdf238d1d2e']
Already enabled.
```
#### Grab IR code to file
```shell
> python orvibo.py -i 192.168.1.37 -t test.ir
Orvibo[type=irda, ip=192.168.1.37, mac=b'accf5378dfdc']
Done
```
#### Emit already grabed IR code
```shell
> python orvibo.py -i 192.168.1.37 -e test.ir
Orvibo[type=irda, ip=192.168.1.37, mac=b'accf5378dfdc']
Done
```


### Python3 module
#### Discovering all devices in the network
```python
from orvibo import Orvibo

for ip in Orvibo.discover():
    print('IP =', ip)

for args in Orvibo.discover().values():
    device = Orvibo(*args)
    print(device)
```
Result
```
IP = 192.168.1.45
IP = 192.168.1.37
Orvibo[type=socket, ip=192.168.1.45, mac=b'acdf238d1d2e']
Orvibo[type=irda, ip=192.168.1.37, mac=b'accf4378efdc']
```

#### Getting exact device by IP
```python
device = Orvibo.discover('192.168.1.45')
print(device)
```
Result:
```
Orvibo[type=socket, ip=192.168.1.45, mac=b'acdf238d1d2e']
```

#### Control S20 wifi socket
**only for devices with type 'socket'**
```python
device = Orvibo('192.168.1.45')
print('Is socket enabled: {}'.format(device.on))
device.on = not device.on # Toggle socket
print('Is socket enabled: {}'.format(device.on))
```
Result:
```
Is socket enabled: True
Is socket enabled: False
```

#### Learning AllOne IR blaster
**only for devices with type 'irda'**
```python
device = Orvibo('192.168.1.37')
ir = device.learn_ir('test.ir', timeout = 15) # AllOne red light is present,
                                              # waiting for ir signal for 15 seconds and stores it to test.ir file

# Emit IR code from "test.ir"
if ir is not None:
    device.emit_ir('test.ir')
    # Or the with the same result
    # device.emit_ir(ir)
```
