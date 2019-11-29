#!/usr/bin/env python3

from pyftdi.ftdi import Ftdi
import pyftdi.serialext
from pyftdi.spi import SpiController
from serial_utils import is_valid_serial_number
import signal
import sys
import subprocess
import logging
import time

sys.path.append("/usr/local/bin")
import icebox


class FPGABoard:
	CDONE = 1 << 6 # ADBUS6
	CRESET = 1 << 7 # ADBUS7
	CS = 1 << 4
	
	def __init__(self, serial_number, baudrate=3000000, timeout=0.5):
		self._log = logging.getLogger(type(self).__name__)
		self._serial_number = serial_number
		self._uart = pyftdi.serialext.serial_for_url(
			"ftdi://::{}/2".format(self._serial_number),
			baudrate=baudrate,
			timeout=timeout
		)
		# there is only one cs connected, but it is ADBUS4, not ADBUS3
		# since ADBUS3 is not used, simply configure two cs' but only use the second one
		self._spi_ctrl = SpiController(cs_count=1)
		# latency=1
		self._spi_ctrl.configure("ftdi://::{}/1".format(self._serial_number), frequency=6e6)
		self._spi = self._spi_ctrl.get_port(0, mode=2)
		self._spi_gpio = self._spi_ctrl.get_gpio()
		self._spi_gpio.set_direction(self.CRESET | self.CDONE | self.CS, self.CRESET | self.CS)
		self._gpio_out = 0
		self._set_creset(True)
	
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
		#self._flash_bitstream_iceprog(bitstream_path)
		self._flash_bitstream_spi(bitstream_path)
	
	def _flash_bitstream_iceprog(self, bitstream_path):
		vid = self._uart.udev.usb_dev.idVendor
		pid = self._uart.udev.usb_dev.idProduct
		sn = self._serial_number
		try:
			self.no_int_subprocess(["iceprog", "-d", "s:0x{:04x}:0x{:04x}:{}".format(vid, pid, sn), "-S", bitstream_path])
		except subprocess.CalledProcessError as cpe:
			print(cpe.output)
			raise
	
	def _flash_bitstream_spi(self, bitstream_path):
		# read bitstream
		with open(bitstream_path, "rb") as bitstream_file:
			bitstream = bitstream_file.read()
		
		self._log.debug("CDONE: {}".format("high" if self._get_cdone() else "low"))
		
		self._set_creset(False)
		
		# chip select to low to trigger configuration as SPI peripheral
		#self._spi.read(0, False, False)
		self._set_cs(False)
		self._spi.flush()
		
		self.usleep(100)
		
		self._set_creset(True)
		self._spi.flush()
		
		# wait for FPGA to clear it's internal configuration memory
		# at least 1200 us
		self.usleep(2000)
		
		# send bitstream
		chunk_size = 4096
		for i in range(0, len(bitstream), chunk_size):
			self._spi.write(bitstream[i:i+chunk_size], False, False)
		
		# chip select to high
		#self._spi.read(0, False, True)
		self._set_cs(True)
		
		# wait 100 SPI clock cycles for CDONE to go high
		self._spi.write(bytes([0x00]*13), False, False)
		self._spi.flush()
		
		# check CDONE
		if self._get_cdone():
			self._log.debug("CDONE: high, programming successful")
		else:
			raise Exception("Programming failed")
		
		# wait at least 49 SPI clock cycles
		self._spi.write(bytes([0x00]*7), False, False)
		self._spi.flush()
		
		# SPI pins now also available as user IO (from the FPGA perspective), but they are not used
	
	def _set_creset(self, high=True):
		self._set_gpio_out(self.CRESET, high)
	
	def _set_cs(self, high=True):
		self._set_gpio_out(self.CS, high)
	
	def _set_gpio_out(self, pin, high):
		if high:
			self._gpio_out |= pin
		else:
			self._gpio_out &= 0xffff ^ pin
		
		self._spi_gpio.write(self._gpio_out)
		
	
	def _get_cdone(self):
		gpio = self._spi_gpio.read()
		return (gpio & self.CDONE) != 0
	
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
	
	@staticmethod
	def usleep(usec):
		time.sleep(usec/1000000)
