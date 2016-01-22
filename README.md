# orvibo
Module to manipulate with Orvibo devices, such as WiFi sockets and AllOne IR blasters

## Refferences
* Module is based on [python-orvibo](https://github.com/happyleavesaoc/python-orvibo) module which currently supports Orvibo S20 sockets.
* Lots of info was found in [ninja-allone](https://github.com/Grayda/ninja-allone/blob/master/lib/allone.js) library
* S20 data analysis by anonymous is [here](http://pastebin.com/0w8N7AJD)

## Usage
### Discovering all devices in the network
```python
for device in orvibo.discover():
    print(device)
```
As result:
```
Orvibo[type=socket, ip=192.168.1.45, mac=b'acdf238d1d2e']
Orvibo[type=irda, ip=192.168.1.37, mac=b'accf4378efdc']
```

### Getting exact device by IP
```python
device = orvibo.discover('192.168.1.45')
print(device)
```
Result:
```
Orvibo[type=socket, ip=192.168.1.45, mac=b'acdf238d1d2e']
```

### Control S20 wifi socket
**only for devices with type 'socket'**
```python
device = orvibo.discover('192.168.1.45')
print('Is socket enabled: {}'.format(device.on))
device.on = not device.on # Toggle socket
print('Is socket enabled: {}'.format(device.on))
```
Result:
```
Is socket enabled: True
Is socket enabled: False
```

### Learning AllOne IR blaster
**only for devices with type 'irda'**
```python
device = orvibo.discover('192.168.1.37')
devise.subscribe()
device.learn_ir()
ir = device.wait_ir(timeout=15) # AllOne red light is present, waitin for ir signal for 15 seconds

# Now you may send the same signal through AllOne
device.emit_ir(ir)
```
