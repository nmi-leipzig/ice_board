#!/usr/bin/env python3

import pyftdi
from pyftdi.usbtools import UsbTools
from pyftdi.ftdi import Ftdi
import binascii
from array import array

# specialized on Lattice iCE40-HX8K Breakout Board
# so a FTDI FT2232H and a 2048 bit EEPROM is expected


class EEAccessor(Ftdi):
	"""specialized to access FT2232H EEPROM"""
	EEPROM_SIZE = 0x100 # in bytes
	
	USE_SERIAL = 0x08
	
	def read_eeprom_word(self, index):
		"""read single word from the EEPROM"""
		#return self._ctrl_transfer_in(Ftdi.SIO_READ_EEPROM, 2)
		return self.usb_dev.ctrl_transfer(Ftdi.REQ_IN, Ftdi.SIO_READ_EEPROM, 0, index, 2, self.usb_read_timeout)
	
	def read_eeprom(self):
		eeprom = array("B")
		for index in range(self.EEPROM_SIZE//2):
			word = self.read_eeprom_word(index)
			eeprom.extend(word)
		
		return eeprom
	
	def _write_eeprom(self, eeprom):
		pass
	
	def set_serial(self, ):
		eeprom = self.read_eeprom()
		if eeprom[0x0a]&self.USE_SERIAL == 0:
			# no serial set
			pass
		else:
			# preexisting serial
			pass

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
		#for i in range(128):
		#	data = dev.read_eeprom(i)
		#	print("{:04x}".format(i*2), binascii.hexlify(data), [chr(b) for b in data])
		print(dev.read_eeprom())
		dev.close()
