#!/usr/bin/env python3

import pyftdi
from pyftdi.usbtools import UsbTools
from pyftdi.ftdi import Ftdi
import binascii
from array import array
import struct
import collections

# specialized on Lattice iCE40-HX8K Breakout Board
# so a FTDI FT2232H and a 2048 bit EEPROM is expected

StringPosition = collections.namedtuple("StringPosition", ["offset", "length"])

class EEAccessor(Ftdi):
	"""specialized to access FT2232H EEPROM"""
	EEPROM_SIZE = 0x100 # in bytes
	STRING_AREA_START = 0x9a
	STRING_AREA_END = 0xf5
	
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
		self.check_eeprom(eeprom)
		print("Would write:")
		for index in range(len(eeprom)//2):
			word = eeprom[index*2:index*2+2]
			print(binascii.hexlify(word))
	
	def set_serial_number(self, serial_number):
		eeprom = self.read_eeprom()
		self.check_eeprom(eeprom)
		
		# check length
		assert len(serial_number) > 0, "Empty serial number"
		serial_pos = StringPosition(eeprom[0x10]+eeprom[0x11], len(serial_number)*2+2)
		assert sum(serial_pos) <= self.STRING_AREA_END, "Serial number too long, ends at address 0x{:02x}".format(sum(serial_pos)-1)
		
		if eeprom[0x0a] & self.USE_SERIAL == 0:
			# no serial number set
			# set serial number flag
			eeprom[0x0a] |= self.USE_SERIAL
		else:
			# preexisting serial number
			# clear serial number, legacy port and PnP
			for addr in range(eeprom[0x12], eeprom[0x12]+eeprom[0x13]+3):
				eeprom[addr] = 0x00
		
		# write new serial number
		eeprom[0x12] = serial_pos.offset
		eeprom[0x13] = serial_pos.length
		
		eeprom[serial_pos.offset] = serial_pos.length
		eeprom[serial_pos.offset+1] = 0x03
		
		addr = serial_pos.offset + 2
		for char in serial_number:
			eeprom[addr] = ord(char)
			eeprom[addr+1] = 0x00
			addr += 2
		
		# write legacy port and PnP
		for value in (0x02, 0x03, 0x00):
			eeprom[addr] = value
			addr += 1
		
		# update checksum
		checksum = self.eeprom_checksum(eeprom)
		checksum_bytes = array("B", struct.pack("<H", checksum))
		eeprom[-2:] = checksum_bytes
		
		self._write_eeprom(eeprom)
	
	@staticmethod
	def eeprom_checksum(eeprom):
		checksum = 0xaaaa
		for i in range(len(eeprom)//2-1):
			word = struct.unpack("<H", eeprom[2*i:2*i+2])[0]
			#print("{:04x}".format(word))
			checksum ^= word
			checksum = ((checksum << 1) | (checksum >> 15)) & 0xffff
		
		#print("{:04x}".format(checksum))
		return checksum
	
	@classmethod
	def check_eeprom(cls, eeprom):
		assert len(eeprom) == cls.EEPROM_SIZE, "EEPROM should be 0x{:x} bytes, but is 0x{:x}".format(cls.EEPROM_SIZE, len(eeprom))
		cls.check_eeprom_checksum(eeprom)
		cls.check_eeprom_strings(eeprom)
	
	@classmethod
	def check_eeprom_checksum(cls, eeprom):
		checksum = cls.eeprom_checksum(eeprom)
		assert eeprom[-1] == (checksum >> 8), "Wrong high byte of EEPROM checksum"
		assert eeprom[-2] == (checksum & 0xff), "Wrong low byte of EEPROM checksum"
	
	@classmethod
	def check_string(cls, eeprom, offset, length):
		assert offset >= cls.STRING_AREA_START, "String begins before string area"
		assert offset+length <= cls.STRING_AREA_END, "String protrudes string area"
		assert eeprom[offset] == length, "Inconsistent string length: 0x{:02x} != 0x{:02x}".format(eeprom[offset], length)
		assert eeprom[offset+1] == 0x03, "Not string type (0x03), but 0x{:02x}".format(eeprom[offset+1])
	
	@classmethod
	def check_eeprom_strings(cls, eeprom):
		# get offsets and length
		manufacturer_pos = StringPosition(eeprom[0x0e], eeprom[0x0f])
		product_pos = StringPosition(eeprom[0x10], eeprom[0x11])
		
		# check individual consistency
		cls.check_string(eeprom, *manufacturer_pos)
		cls.check_string(eeprom, *product_pos)
		
		# check overall consistency
		assert manufacturer_pos.offset == cls.STRING_AREA_START, "Manufacturer string doesn't start at begin of string area"
		assert product_pos.offset == sum(manufacturer_pos), "Product string doesn't start directly after manufacturer string"
		
		# check optional serial number
		if eeprom[0x0a] & cls.USE_SERIAL == 0:
			# no serial number set
			assert eeprom[0x12] == 0x00, "Serial number not used but offset set"
			assert eeprom[0x13] == 0x00, "Serial number not used but length set"
		else:
			# serial number set
			serial_pos = StringPosition(eeprom[0x12], eeprom[0x13])
			cls.check_string(eeprom, *serial_pos)
			
			assert serial_pos.offset == sum(product_pos), "Serial number doesn't start directly after product string"
			serial_end = sum(serial_pos)
			assert eeprom[serial_end] == 0x02, "Unexpected value for legacy port high byte"
			assert eeprom[serial_end+1] == 0x03, "Unexpected value for legacy port low byte"
			assert eeprom[serial_end+2] == 0x00, "Unexpected value for PnP"

if __name__ == "__main__":
	#devices = [f[0] for f in Ftdi.find_all([(0x0403, 0x6010)], True) if f[0].sn is not None]
	#devices = [f[0] for f in Ftdi.get_identifiers("ftdi:///?")]
	devices = [f[0] for f in Ftdi.find_all([(0x0403, 0x6010)], True)]
	print(devices)
	desc = devices[0]
	print(desc)
	dev = EEAccessor()
	for index, desc in enumerate(devices):
		dev.open_from_url("ftdi://::{:x}:{:x}/1".format(desc.bus, desc.address))
		print("MPSSE: {}".format(dev.has_mpsse))
		#for i in range(128):
		#	data = dev.read_eeprom(i)
		#	print("{:04x}".format(i*2), binascii.hexlify(data), [chr(b) for b in data])
		print(binascii.hexlify(dev.read_eeprom()))
		#eeprom = dev.read_eeprom()
		#eeprom[-1] += 1
		#dev.check_eeprom(eeprom)
		dev.set_serial_number("E89000")
		
		dev.close()
