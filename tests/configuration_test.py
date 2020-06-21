import os
import sys
from typing import NamedTuple
import time

import avocado

sys.path.append(
	os.path.dirname(
		os.path.dirname(os.path.abspath(__file__))
	)
)

from configuration import Configuration

class ASCEntry(NamedTuple):
	name: str
	line_data: tuple

class ConfigurationTest(avocado.Test):
	
	def test_device_from_asc(self):
		asc_path = self.get_data("echo.asc", must_exist=True)
		with open(asc_path, "r") as asc_file:
			res = Configuration.device_from_asc(asc_file)
		
		self.assertEqual("8k", res)
	
	def test_creation(self):
		res = Configuration.create_blank()
	
	def test_create_from_asc(self):
		asc_path = self.get_data("echo.asc", must_exist=True)
		res = Configuration.create_from_asc(asc_path)
	
	def test_get_bits(self):
		pass
	
	def test_set_bits(self):
		pass
	
	def test_asc_compare(self):
		"""self test for the assert_structural_equal method """
		
		echo_path = self.get_data("echo.asc", must_exist=True)
		send_path = self.get_data("send_all_bram.512x8.asc", must_exist=True)
		
		with open(echo_path, "r") as asc_file_a, open(echo_path, "r") as asc_file_b:
			self.assert_structural_equal(asc_file_a, asc_file_b)
		
		with open(echo_path, "r") as asc_file_a, open(send_path, "r") as asc_file_b:
			with self.assertRaises(AssertionError):
				self.assert_structural_equal(asc_file_a, asc_file_b)
		
	
	def assert_structural_equal(self, asc_file_a, asc_file_b):
		parts_a = self.load_asc_parts(asc_file_a)
		parts_b = self.load_asc_parts(asc_file_b)
		
		self.assertEqual(parts_a, parts_b)
	
	@staticmethod
	def load_asc_parts(asc_file):
		asc_dict = {}
		prev_data = None
		for line in asc_file:
			line = line.strip()
			if line[0] == ".":
				line_parts = line.split()
				entry = ASCEntry(line_parts[0], tuple(line_parts[1:]))
				assert entry not in asc_dict, f"multiple entries for {entry}"
				prev_data = []
				asc_dict[entry] = prev_data
			else:
				prev_data.append(line)
		
		return asc_dict

