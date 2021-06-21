#!/usr/bin/env python3

import os
import sys
from array import array
import random
import unittest.mock as mock
import unittest

from pyftdi.usbtools import UsbDeviceDescriptor

from ..configuration import Configuration
from ..fpga_board import FPGABoard

class FPGABoardTest(unittest.TestCase):
	@staticmethod
	def get_data(filename, must_exist=False):
		path = os.path.join(f"{__file__}.data", filename)
		return path
	
	def setUp(self):
		self.valid_sn =  "T80000"
		self.dev_list = [
			(UsbDeviceDescriptor(0x0403, 0x6010, 3, 6, "T8S001", 0, "invalid number of interfaces"), 1),
			(UsbDeviceDescriptor(0x0403, 0x6010, 3, 6, "T80002", 0, "invalid serial"), 2),
			(UsbDeviceDescriptor(0x0403, 0x6010, 3, 7, self.valid_sn, 0, "valid board"), 2),
		]
	
	def test_get_suitable_serial_numbers(self):
		other_sn = "T8P002"
		self.dev_list.append(
			(UsbDeviceDescriptor(0x0403, 0x6010, 2, 7, other_sn, 0, "second valid board"), 2)
		)
		with mock.patch("pyftdi.ftdi.Ftdi.find_all", side_effect=lambda v, p: self.dev_list):
			res = FPGABoard.get_suitable_serial_numbers()
			
			set_res = set(res)
			self.assertEqual(len(res), len(set_res), "some serial numbers returned multiple times")
			self.assertEqual({self.valid_sn, other_sn}, set_res, "some unexpected or some missing serial numbers")
	
	def test_get_suitable_board(self):
		baudrate = 968123
		timeout = 8.1
		with mock.patch("pyftdi.ftdi.Ftdi.find_all", side_effect=lambda v, p: self.dev_list), mock.patch.object(FPGABoard, "__init__", autospec=True, return_value=None) as mock_init:
			res = FPGABoard.get_suitable_board(baudrate, timeout)
			
			mock_init.assert_called_once_with(res, self.valid_sn, baudrate, timeout)
	
	@unittest.skipIf(len(FPGABoard.get_suitable_serial_numbers())<1, "no suitable boards found")
	def test_flash_bitstream_file(self):
		"""
		:avocado: tags=hil
		"""
		data_length = 10
		bitstream_path = self.get_data("echo_fpga.bin")
		with FPGABoard.get_suitable_board() as fpga:
			fpga.flash_bitstream_file(bitstream_path)
			data = bytes(random.choices(range(256), k=data_length))
			fpga.uart.write(data)
			read_data = fpga.uart.read(data_length)
			self.assertEqual(data, read_data, "Received data differs from send data; Echo botstream not working")
	
	@unittest.skipIf(len(FPGABoard.get_suitable_serial_numbers())<1, "no suitable boards found")
	def test_flash_bitstream(self):
		"""
		:avocado: tags=hil
		"""
		data_length = 10
		bitstream_path = self.get_data("echo_fpga.bin")
		with open(bitstream_path, "rb") as bin_file:
			bitstream = bin_file.read()
		
		with FPGABoard.get_suitable_board() as fpga:
			fpga.flash_bitstream(bitstream)
			data = bytes(random.choices(range(256), k=data_length))
			fpga.uart.write(data)
			read_data = fpga.uart.read(data_length)
			self.assertEqual(data, read_data, "Received data differs from send data; Echo botstream not working")
	
	@unittest.skipIf(len(FPGABoard.get_suitable_serial_numbers())<1, "no suitable boards found")
	def test_configure(self):
		"""
		:avocado: tags=hil
		"""
		data_length = 10
		asc_path = self.get_data("echo_fpga.asc")
		config = Configuration.create_from_asc(asc_path)
		
		with FPGABoard.get_suitable_board() as fpga:
			fpga.configure(config)
			data = bytes(random.choices(range(256), k=data_length))
			fpga.uart.write(data)
			read_data = fpga.uart.read(data_length)
			self.assertEqual(data, read_data, "Received data differs from send data; Echo botstream not working")
