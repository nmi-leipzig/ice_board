#!/usr/bin/env python3

import os
import sys
from array import array
import unittest.mock as mock
import random
import logging
import unittest

from pyftdi.usbtools import UsbDeviceDescriptor
from deap import tools
from deap import creator
from deap import base
from deap import algorithms

sys.path.append(
	os.path.dirname(
		os.path.dirname(os.path.abspath(__file__))
	)
)

from ..fpga_manager import get_fpga_board, FPGAManager
from ..fpga_board import FPGABoard
from ..serial_utils import is_valid_serial_number

class FPGAManagerTest(unittest.TestCase):
	def generate_creation_data_set(self, valid, invalid):
		"""Generate data set for FPGAManger creation
		
		valid: number of viable device descriptors
		invalid: number of not viable device descriptors
		"""
		valid_sn = ['T80000', 'T8S001', 'T8P002', 'T8M003', 'T8J004', 'T8G005', 'T8D006', 'T8A007', 'T87008', 'T84009']
		dev_list = []
		sn_list = []
		dev_nr = 2
		
		for i in range(valid):
			sn = valid_sn[i]
			sn_list.append(sn)
			dev_list.append(
				(UsbDeviceDescriptor(0x0403, 0x6010, 3, dev_nr, sn, 0, "valid device {}".format(i)), 2)
			)
		
		valid_index = valid
		for j in range(invalid):
			if j % 2 == 0:
				dev_list.append((UsbDeviceDescriptor(
					0x0403,
					0x6010,
					3,
					dev_nr,
					"X"*j,
					0,
					"invalid device {}, invalid serialnumber".format(j)
				), 2))
			else:
				dev_list.append((UsbDeviceDescriptor(
					0x0403,
					0x6010,
					3,
					dev_nr,
					valid_sn[valid_index],
					0,
					"invalid device {}, wrong number of interfaces".format(j)
				), 1))
				valid_index += 1
				
			dev_nr += 1
		
		return dev_list, sn_list
	
	def generic_creation_test(self, expected_serial_numbers, dev_list, min_nr, max_nr, requested_serial_numbers):
		baudrate = 968123
		timeout = 8.1
		
		with mock.patch("pyftdi.ftdi.Ftdi.find_all", side_effect=lambda v, p: dev_list):
			res = FPGAManager.create_manager(min_nr, max_nr, requested_serial_numbers, baudrate, timeout)
			
			if expected_serial_numbers is None:
				# don't check generated serial numbers
				return
			
			created_sn_list = list(res._avail_dict)
			created_sn_set = set(created_sn_list)
			self.assertEqual(len(created_sn_list), len(created_sn_set), "Serial numbers added multiple times")
			expected_sn_set = set(expected_serial_numbers)
			self.assertEqual(expected_sn_set, created_sn_set, "Serial numbers of created managed boards differ from expected")
		
	
	def generic_creation_error_test(self, expected_exception, dev_list, min_nr, max_nr, requested_serial_numbers):
		with self.assertRaises(expected_exception):
			self.generic_creation_test(None, dev_list, min_nr, max_nr, requested_serial_numbers)
	
	def test_creation(self):
		dev_list, sn_list = self.generate_creation_data_set(5, 3)
		
		# no requested, no upper limit
		self.generic_creation_test(sn_list, dev_list, 1, 0, [])
		
		# some requested, no upper limit
		self.generic_creation_test(sn_list, dev_list, 1, 0, sn_list[1:2])
		
		# all requested, no upper limit
		self.generic_creation_test(sn_list, dev_list, 1, 0, sn_list)
		
		# no requested, lower limit
		self.generic_creation_test(sn_list, dev_list, 2, 0, [])
		
		# some requested, lower limit
		self.generic_creation_test(sn_list, dev_list, 2, 0, sn_list[1:2])
		
		# all requested, lower limit
		self.generic_creation_test(sn_list, dev_list, 2, 0, sn_list)
		
		# no requested, upper limit
		self.generic_creation_test(sn_list[:3], dev_list, 2, 3, [])
		
		# some requested, upper limit
		self.generic_creation_test(sn_list[:3], dev_list, 2, 3, sn_list[1:2])
		
		# all requested, upper limit
		self.generic_creation_test(sn_list[:3], dev_list, 2, 3, sn_list[:3])
	
	def test_creation_input_error(self):
		dev_list, sn_list = self.generate_creation_data_set(5, 3)
		
		# too low minimum
		self.generic_creation_error_test(ValueError, dev_list, 0, 0, [])
		
		# more requested than maximum
		self.generic_creation_error_test(ValueError, dev_list, 1, 4, sn_list)
		
		# minimum greater than maximum
		self.generic_creation_error_test(ValueError, dev_list, 5, 3, [])
		
		# serial number requested multiple times
		self.generic_creation_error_test(ValueError, dev_list, 0, 0, sn_list[:3]+sn_list[1:2])
		
		# requested serial number not valid
		invalid_sn = [e[0].sn for e in dev_list if not is_valid_serial_number(e[0].sn)]
		self.generic_creation_error_test(ValueError, dev_list, 1, 0, sn_list+invalid_sn[:1])
	
	def test_creation_unavailable_error(self):
		dev_list, sn_list = self.generate_creation_data_set(5, 3)
		
		# minimum not reached
		self.generic_creation_error_test(OSError, dev_list, 6, 0, [])
		
		# requested serial number not available
		red_dev_list = [e for e in dev_list if e[0].sn != sn_list[1]]
		self.generic_creation_error_test(OSError, red_dev_list, 1, 0, sn_list[:3])
		
		# requested serial number not valid device (e.g. wrong number of interfaces)
		red_dev_list = list(map(lambda e: (e[0], 1) if e[0].sn==sn_list[1] else e, dev_list))
		self.generic_creation_error_test(OSError, red_dev_list, 1, 0, sn_list[:3])
	
	def run_ga(self, toolbox):
		pop = toolbox.init_pop(n=10)
		algorithms.eaSimple(pop, toolbox, cxpb=0.5, mutpb=0.1, ngen=5)
	
	@unittest.skipIf(len(FPGABoard.get_suitable_serial_numbers())<1, "no suitable boards found")
	def test_multi(self):
		toolbox = create_toolbox()
		# add the directory of this file to the path so pickle can find this module when pickling
		# necessary for execution with avocado
		sys.path.append(os.path.dirname(os.path.abspath(__file__)))
		
		fm = FPGAManager.create_manager()
		pool = fm.generate_pool()
		toolbox.register("map", pool.map)
		
		toolbox.register("evaluate", max_true)
		
		self.run_ga(toolbox)
		
		pool.close()
		pool.join()
		
		fm.close()

def max_true(individual):
	with get_fpga_board() as fpga_board:
		#print("Board in eval: {} {}".format(fpga_board.serial_number, hex(id(fpga_board))))
		fpga_board.flash_bitstream_file(os.path.join(f"{__file__}.data", "sum_fpga.bin"))
		#print("send individual")
		fpga_board.uart.write(bytes(individual))
		#print("read sum")
		raw_data = fpga_board.uart.read(1)
		s = int.from_bytes(raw_data, 'little')
		#print("{} = sum({})".format(s, individual))
	#print("FM in eval: {}".format(get_fpga_manager()))
	#s = sum(individual)
	return (s, )

creator.create("TestFit", base.Fitness, weights=(1.0,))
creator.create("Chromo", list, fitness=creator.TestFit)

def create_toolbox():
	
	toolbox = base.Toolbox()
	
	toolbox.register("rand_bool", random.randint, 0, 1)
	toolbox.register("init_individual", tools.initRepeat, creator.Chromo, toolbox.rand_bool, 20)
	toolbox.register("init_pop", tools.initRepeat, list, toolbox.init_individual)
	
	toolbox.register("mate", tools.cxTwoPoint)
	toolbox.register("mutate", tools.mutFlipBit, indpb=0.05)
	toolbox.register("select", tools.selTournament, tournsize=3)
	
	return toolbox


if __name__ == "__main__":
	#os.environ["LIBUSB_DEBUG"] = "4"
	logging.basicConfig(level=logging.DEBUG)
	
	
	toolbox = create_toolbox()
	toolbox.register("evaluate", max_true)
	
	random.seed(64)
	
	fm = FPGAManager.create_manager()
	#pool = fm.generate_pool(1)
	pool = fm.generate_pool(log_level=logging.root.level)
	toolbox.register("map", pool.map)
	
	pop = toolbox.init_pop(n=5)
	
	#input("go on?")
	
	algorithms.eaSimple(pop, toolbox, cxpb=0.5, mutpb=0.1, ngen=5)
	
	pool.close()
	pool.join()
	
	fm.close()
