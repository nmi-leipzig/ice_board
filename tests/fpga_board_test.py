#!/usr/bin/env python3

import os
import sys
from array import array
import unittest.mock as mock

from avocado import Test
from pyftdi.usbtools import UsbDeviceDescriptor

sys.path.append(
	os.path.dirname(
		os.path.dirname(os.path.abspath(__file__))
	)
)

from fpga_board import FPGABoard

class FPGABoardTest(Test):
	def test_get_suitable_board(self):
		serial_number =  "T80000"
		baudrate = 968123
		timeout = 8.1
		dev_list = [
			(UsbDeviceDescriptor(0x0403, 0x6010, 3, 6, "T8S001", 0, "invalid number of interfaces"), 1),
			(UsbDeviceDescriptor(0x0403, 0x6010, 3, 6, "T80002", 0, "invalid serial"), 2),
			(UsbDeviceDescriptor(0x0403, 0x6010, 3, 7, serial_number, 0, "valid board"), 2),
		]
		with mock.patch("pyftdi.ftdi.Ftdi.find_all", side_effect=lambda v, p: dev_list), mock.patch("fpga_board_test.FPGABoard.__init__", autospec=True, return_value=None) as mock_init:
			res = FPGABoard.get_suitable_board(baudrate, timeout)
			
			mock_init.assert_called_once_with(res, serial_number, baudrate, timeout)
