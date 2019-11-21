#!/usr/bin/env python3

import pyftdi
from pyftdi.usbtools import UsbTools
from pyftdi.ftdi import Ftdi
import binascii

class EEAccessor(Ftdi):
	
	def read_eeprom(self, addr):
		#return self._ctrl_transfer_in(Ftdi.SIO_READ_EEPROM, 2)
		return self.usb_dev.ctrl_transfer(Ftdi.REQ_IN, Ftdi.SIO_READ_EEPROM, 0, addr, 2, self.usb_read_timeout)

if __name__ == "__main__":
	#devices = [f[0] for f in Ftdi.find_all([(0x0403, 0x6010)], True) if f[0].sn is not None]
	#devices = [f[0] for f in Ftdi.get_identifiers("ftdi:///?")]
	devices = [f[0] for f in Ftdi.find_all([(0x0403, 0x6010)], True)]
	print(devices)
	desc = devices[0]
	print(desc)
	dev = EEAccessor()
	for index, desc in enumerate(devices):
		dev.open_from_url("ftdi://::{}:{}/1".format(desc.bus, desc.address))
		print("MPSSE: {}".format(dev.has_mpsse))
		for i in range(128):
			data = dev.read_eeprom(i)
			print("{:04x}".format(i*2), binascii.hexlify(data), [chr(b) for b in data])
		dev.close()
