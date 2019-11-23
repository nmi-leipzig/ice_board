#!/usr/bin/env python3

import pyftdi
from pyftdi.usbtools import UsbTools
from pyftdi.ftdi import Ftdi
import binascii
from array import array
import struct
import collections
import logging
import argparse
import re
import sys

StringPosition = collections.namedtuple("StringPosition", ["offset", "length"])
DeviceNode = collections.namedtuple("DeviceNode", ["bus", "address"])

class SerialWriter(Ftdi):
	"""specialized version to write serial numbers to FT2232H EEPROM
	
	specialized on Lattice iCE40-HX8K Breakout Boards
	so a FTDI FT2232H and a 2048 bit EEPROM is expected
	"""
	EEPROM_SIZE = 0x100 # in bytes
	STRING_AREA_START = 0x9a # first address in string area
	STRING_AREA_LIMIT = 0xf6 # first address after string area
	
	USE_SERIAL = 0x08
	
	def read_eeprom_word(self, index):
		"""read single word from the EEPROM"""
		return self.usb_dev.ctrl_transfer(Ftdi.REQ_IN, Ftdi.SIO_READ_EEPROM, 0, index, 2, self.usb_read_timeout)
	
	def read_eeprom(self):
		eeprom = array("B")
		for index in range(self.EEPROM_SIZE//2):
			word = self.read_eeprom_word(index)
			eeprom.extend(word)
		
		return eeprom
	
	def _write_eeprom_word(self, index, word):
		self.log.debug("EEPROM word 0x{:02x} write {}".format(index, binascii.hexlify(word)))
		value = struct.unpack("<H", word)[0]
		return self.usb_dev.ctrl_transfer(Ftdi.REQ_OUT, Ftdi.SIO_WRITE_EEPROM, value, index, 2, self.usb_read_timeout)
	
	def _write_eeprom(self, eeprom):
		self.check_eeprom(eeprom)
		
		# preparation
		self._reset_device()
		self.poll_modem_status()
		self.set_latency_timer(0x77)
		
		for index in range(len(eeprom)//2):
			word = eeprom[index*2:index*2+2]
			self._write_eeprom_word(index, word)
	
	def set_serial_number_device(self, serial_number):
		"""set new serial number to currently opened device"""
		eeprom = self.read_eeprom()
		self.check_eeprom(eeprom)
		
		self.set_serial_number_eeprom(eeprom, serial_number)
		
		self._write_eeprom(eeprom)
	
	@classmethod
	def set_serial_number_eeprom(cls, eeprom, serial_number):
		"""set serial number in EEPROM data"""
		
		# check length
		assert len(serial_number) > 0, "Empty serial number"
		serial_pos = StringPosition(eeprom[0x10]+eeprom[0x11], len(serial_number)*2+2)
		assert sum(serial_pos) <= cls.STRING_AREA_LIMIT, "Serial number too long, ends at address 0x{:02x}".format(sum(serial_pos)-1)
		
		if eeprom[0x0a] & cls.USE_SERIAL == 0:
			# no serial number set
			# set serial number flag
			eeprom[0x0a] |= cls.USE_SERIAL
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
		checksum = cls.eeprom_checksum(eeprom)
		checksum_bytes = array("B", struct.pack("<H", checksum))
		eeprom[-2:] = checksum_bytes
	
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
		assert offset+length <= cls.STRING_AREA_LIMIT, "String protrudes string area"
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
	
	@classmethod
	def find_lattice(cls):
		ft2232_devices = cls.find_all([(0x0403, 0x6010)], True)
		lattice_devices = [f[0] for f in ft2232_devices if f[0].description=="Lattice FTUSB Interface Cable"]
		return lattice_devices

def parse_device(string):
	res = re.match(r"(?P<bus>\d+):(?P<address>\d+)", string)
	if res is not None:
		return DeviceNode(int(res.group("bus")), int(res.group("address")))
	
	raise argparse.ArgumentTypeError("'{}' is not a valid device specification".format(string))

def create_argument_parser():
	arg_parser = argparse.ArgumentParser()
	arg_parser.set_defaults(func=None)
	sub_parser = arg_parser.add_subparsers()
	
	arg_read = sub_parser.add_parser("read")
	arg_read.add_argument("-o", "--output", default=None, type=argparse.FileType("wb"), help="name of the output file")
	arg_read.add_argument("-d", "--device", default=None, type=parse_device, help="specification of the USB device in the form bus:address")
	arg_read.set_defaults(func=read_eeprom)
	
	arg_sn = sub_parser.add_parser("serial_number", aliases=["sn"])
	arg_sn.set_defaults(func=set_serial_number)
	
	return arg_parser

def read_eeprom(arguments):
	if arguments.device is None:
		logging.warning("No device specified, take first suitable device")
		devices = SerialWriter.find_lattice()
		try:
			desc = DeviceNode(devices[0].bus, devices[0].address)
		except IndexError:
			logging.error("No suitable device connected")
			sys.exit(-1)
	else:
		desc = arguments.device
	dev = SerialWriter()
	dev.open_from_url("ftdi://::{:x}:{:x}/1".format(desc.bus, desc.address))
	eeprom = dev.read_eeprom()
	dev.close()
	if arguments.output is None:
		print("EEPROM from {}:".format(desc), end="")
		for addr, value in enumerate(eeprom):
			if addr%2 == 0:
				print("\n{:02x}: ".format(addr), end="")
			print("{:02x}".format(value), end="")
		print()
		
	else:
		arguments.output.write(eeprom)

def set_serial_number(arguments):
	pass

if __name__ == "__main__":
	logging.basicConfig(level=logging.DEBUG)
	
	parser = create_argument_parser()
	arguments = parser.parse_args()
	
	if arguments.func is None:
		parser.print_help()
	else:
		arguments.func(arguments)
