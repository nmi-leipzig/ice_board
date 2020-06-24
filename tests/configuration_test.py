import os
import sys
from typing import NamedTuple
import time
import json

import avocado

sys.path.append(
	os.path.dirname(
		os.path.dirname(os.path.abspath(__file__))
	)
)

from configuration import Configuration
from device_data import TilePosition, Bit

class ASCEntry(NamedTuple):
	name: str
	line_data: tuple

class ConfigurationTest(avocado.Test):
	
	def test_device_from_asc(self):
		asc_path = self.get_data("send_all_bram.512x8.asc", must_exist=True)
		with open(asc_path, "r") as asc_file:
			res = Configuration.device_from_asc(asc_file)
		
		self.assertEqual("8k", res)
	
	def test_creation(self):
		res = Configuration.create_blank()
	
	def test_create_from_asc(self):
		asc_path = self.get_data("send_all_bram.512x8.asc", must_exist=True)
		res = Configuration.create_from_asc(asc_path)
		
		# check logic cell
		data_path = self.get_data("send_all_bram.512x8.json", must_exist=True)
		with open(data_path, "r") as data_file:
			data = json.load(data_file)
		tile_pos = TilePosition(*data[0])
		
		tile_data = tuple(data[1])
		
		self.assertEqual(tile_data, res._tiles[tile_pos])
		
		# check bram
		bram_pos = TilePosition(*data[2])
		bram_data = tuple(data[3])
		
		self.assertEqual(bram_data, res._bram[bram_pos][:len(bram_data)])
		rest = tuple([False]*len(bram_data[0]) for _ in range(len(res._bram[bram_pos])-len(bram_data)))
		self.assertEqual(rest, res._bram[bram_pos][len(bram_data):])
	
	def test_get_bits(self):
		asc_path = self.get_data("send_all_bram.512x8.asc", must_exist=True)
		res = Configuration.create_from_asc(asc_path)
		
		data_path = self.get_data("send_all_bram.512x8.json", must_exist=True)
		with open(data_path, "r") as data_file:
			data = json.load(data_file)
		tile_pos = TilePosition(*data[0])
		
		tile_data = tuple(data[1])
		
		# single bits
		for group in range(len(tile_data)):
			for index in range(len(tile_data[0])):
				bits = (Bit(group, index), )
				values = res.get_bits(tile_pos, bits)
				expected = (tile_data[group][index], )
				self.assertEqual(expected, values)
	
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

