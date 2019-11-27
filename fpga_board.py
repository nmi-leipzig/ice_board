#!/usr/bin/env python3

from pyftdi.ftdi import Ftdi
import pyftdi.serialext
from serial_utils import is_valid_serial_number
import signal
import sys
import subprocess

sys.path.append("/usr/local/bin")
import icebox


class FPGABoard:
	def __init__(self, serial_number, baudrate=3000000, timeout=0.5):
		self._serial_number = serial_number
		self._uart = pyftdi.serialext.serial_for_url(
			"ftdi://::{}/2".format(self._serial_number),
			baudrate=baudrate,
			timeout=timeout
		)
	
	@property
	def uart(self):
		return self._uart
	
	@property
	def serial_number(self):
		return self._serial_number
	
	def __enter__(self):
		return self
	
	def __exit__(self, exc_type, exc_value, traceback):
		self._uart.close()
	
	def flash_bitstream(self, bitstream_path):
		vid = self._uart.udev.usb_dev.idVendor
		pid = self._uart.udev.usb_dev.idProduct
		sn = self._serial_number
		try:
			self.no_int_subprocess(["iceprog", "-d", "s:0x{:04x}:0x{:04x}:{}".format(vid, pid, sn), "-S", bitstream_path])
		except subprocess.CalledProcessError as cpe:
			print(cpe.output)
			raise
	
	@classmethod
	def pack_bitstream(cls, asc_name, bitstream_name):
		cls.no_int_subprocess(["icepack", asc_name, bitstream_name])
	
	@staticmethod
	def ignore_sigint():
		signal.signal(signal.SIGINT, signal.SIG_IGN)
	
	@classmethod
	def no_int_subprocess(cls, cmd):
		"""run subprocess so it doesn't receive SIGINT"""
		
		out = subprocess.check_output(
			cmd,
			stdin=subprocess.DEVNULL,
			stderr=subprocess.STDOUT,
			preexec_fn=cls.ignore_sigint,
			#text=True, # only from Python version 3.7 on
			universal_newlines=True
		)
		return out
	
	@classmethod
	def get_suitable_board(cls, baudrate=3000000, timeout=0.5):
		ft2232_devices = Ftdi.find_all([(0x0403, 0x6010)], True)
		
		suitable = []
		for desc, i_count in ft2232_devices:
			if is_valid_serial_number(desc.sn) and i_count==2:
				suitable.append(desc.sn)
		
		if len(suitable) == 0:
			raise Exception("No suitable devices found.")
		
		return cls(suitable[0], baudrate, timeout)
