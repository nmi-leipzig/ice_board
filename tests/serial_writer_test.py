#!/usr/bin/env python3

import os
import sys
from array import array
import json

from avocado import Test

sys.path.append(
	os.path.dirname(
		os.path.dirname(os.path.abspath(__file__))
	)
)

from serial_writer import SerialWriter

class SerialWriterTest(Test):
	"""
	:avocado: tags=components,quick
	"""
	
	def setUp(self):
		self.with_serial = "eeprom_serial.bin"
		self.without_serial = "eeprom_no_serial.bin"
		self.serial = "E86001"
	
	def eeprom_from_file(self, filename):
		path = self.get_data(filename, must_exist=True)
		with open(path, "rb") as eeprom_file:
			eeprom = array("B", eeprom_file.read())
		
		return eeprom
	
	def generic_good_check_test(self, test_func):
		for filename in (self.with_serial, self.without_serial):
			eeprom = self.eeprom_from_file(filename)
			
			test_func(eeprom)
	
	def test_eeprom_check_good(self):
		self.generic_good_check_test(SerialWriter.check_eeprom)
	
	def test_check_eeprom_checksum_good(self):
		self.generic_good_check_test(SerialWriter.check_eeprom_checksum)
	
	def test_check_eeprom_strings_good(self):
		self.generic_good_check_test(SerialWriter.check_eeprom_strings)
	
	def test_set_serial_number_eeprom(self):
		eeprom = self.eeprom_from_file(self.without_serial)
		expected = self.eeprom_from_file(self.with_serial)
		
		SerialWriter.set_serial_number_eeprom(eeprom, self.serial)
		
		self.assertEqual(expected, eeprom, "Writing serial number had unexpected result")
		
		# overwrite own number -> no change expected
		eeprom = self.eeprom_from_file(self.with_serial)
		
		SerialWriter.set_serial_number_eeprom(eeprom, self.serial)
		
		self.assertEqual(expected, eeprom, "Writing serial number had unexpected result")
	
	def test_serial_number_length(self):
		original = self.eeprom_from_file(self.without_serial)
		start = original[0x10] + original[0x11]
		limit = 0xf6
		
		for length in range(1, (limit-start)//2):
			eeprom = original[:]
			serial_number = "f"*length
			SerialWriter.set_serial_number_eeprom(eeprom, serial_number)
		
		for length in range((limit-start)//2, (0x100-start)//2):
			eeprom = original[:]
			serial_number = "f"*length
			with self.assertRaises(AssertionError):
				SerialWriter.set_serial_number_eeprom(eeprom, serial_number)
	
	def test_assertions_in_checks(self):
		path = self.get_data("faulty_eeprom.json", must_exist=True)
		with open(path, "r") as json_file:
			case_dict = json.load(json_file)
		
		for filename, faulty in case_dict.items():
			eeprom = self.eeprom_from_file(filename)
			
			for raises_error, check_func in zip(faulty, (
				SerialWriter.check_eeprom,
				SerialWriter.check_eeprom_checksum,
				SerialWriter.check_eeprom_strings
			)):
				if raises_error:
					with self.assertRaises(AssertionError):
						check_func(eeprom)
				else:
					check_func(eeprom)
