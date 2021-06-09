#!/usr/bin/env python3
import os
import sys
from dataclasses import dataclass
from typing import NamedTuple, List
import time
import json

import unittest

from ..configuration import Configuration
from ..device_data import TilePosition, BRAMMode, Bit

sys.path.append("/usr/local/bin")
def load_icebox():
	try:
		import icebox
	except ModuleNotFoundError:
		return False
	return True

class ASCEntry(NamedTuple):
	name: str
	line_data: tuple

@dataclass
class SendBRAMMeta:
	mode: BRAMMode
	asc_filename: str
	ram_block: TilePosition
	initial_data: List[int]
	mask: int
	
	def __post_init__(self):
		if isinstance(self.mode, str):
			self.mode = BRAMMode[self.mode]
		self.ram_block = TilePosition(*self.ram_block)

class ConfigurationTest(unittest.TestCase):
	@staticmethod
	def get_data(filename, must_exist=False):
		path = os.path.join(f"{__file__}.data", filename)
		return path
	
	def load_send_bram_meta(self):
		json_path = self.get_data("send_all_bram.json", must_exist=True)
		with open(json_path, "r") as json_file:
			send_bram_meta = tuple([SendBRAMMeta(*s) for s in json.load(json_file)])
		
		return send_bram_meta
	
	def test_device_from_asc(self):
		asc_path = self.get_data("send_all_bram.512x8.asc", must_exist=True)
		with open(asc_path, "r") as asc_file:
			config = Configuration.device_from_asc(asc_file)
		
		self.assertEqual("8k", config)
	
	def test_creation(self):
		config = Configuration.create_blank()
	
	def test_create_from_asc(self):
		asc_path = self.get_data("send_all_bram.512x8.asc", must_exist=True)
		config = Configuration.create_from_asc(asc_path)
		
		# check logic cell
		data_path = self.get_data("send_all_bram.512x8.json", must_exist=True)
		with open(data_path, "r") as data_file:
			data = json.load(data_file)
		tile_pos = TilePosition(*data[0])
		
		tile_data = tuple(data[1])
		
		self.assertEqual(tile_data, config._tiles[tile_pos])
		
		# check bram
		bram_pos = TilePosition(*data[2])
		bram_data = tuple(data[3])
		
		self.assertEqual(bram_data, config._bram[bram_pos][:len(bram_data)])
		rest = tuple([False]*len(bram_data[0]) for _ in range(len(config._bram[bram_pos])-len(bram_data)))
		self.assertEqual(rest, config._bram[bram_pos][len(bram_data):])
	
	def test_write_asc(self):
		asc_path = self.get_data("send_all_bram.512x8.asc", must_exist=True)
		config = Configuration.create_from_asc(asc_path)
		
		with open(asc_path, "r") as org, open("tmp.test_write_asc.asc", "w+") as res:
			config.write_asc(res)
			res.seek(0)
			self.assert_structural_equal(org, res)
	
	@unittest.skipUnless(load_icebox(), "icebox unavailable")
	def test_write_asc_icestorm(self):
		# test writing asc based on iceconfig
		import icebox
		
		asc_path = self.get_data("send_all_bram.512x8.asc", must_exist=True)
		config = Configuration.create_from_asc(asc_path)
		
		expected_ic = icebox.iceconfig()
		expected_ic.read_file(asc_path)
		
		out_path = "tmp.test_write_asc.asc"
		with open(out_path, "w") as res:
			config.write_asc(res)
		
		res_ic = icebox.iceconfig()
		res_ic.read_file(out_path)
		
		self.check_configuration(expected_ic, res_ic)
		
		os.remove(out_path)
	
	def check_configuration(self, expected_config, config):
		# compare two icebox configurations
		for value_name in ("device", "warmboot"):
			expected_value = getattr(expected_config, value_name)
			given_value = getattr(config, value_name)
			self.assertEqual(expected_value, given_value, f"Expected {value_name} to be {expected_value}, but was {given_value}.")
		
		for col_name in ("ram_data", ):
			expected_col = getattr(expected_config, col_name)
			given_col = getattr(config, col_name)
			
			for pos in expected_col:
				if pos not in given_col and all(all(s=="0" for s in r) for r in expected_col[pos]):
					continue
				self.assertIn(pos, given_col)
				self.assertEqual(expected_col[pos], given_col[pos])
			for pos in given_col:
				if pos not in expected_col and all(all(s=="0" for s in r) for r in given_col[pos]):
					continue
				self.assertIn(pos, expected_col)
				self.assertEqual(expected_col[pos], given_col[pos])
		
		for col_name in ("logic_tiles", "io_tiles", "ramb_tiles", "ramt_tiles", "ipcon_tiles", "symbols", "extra_bits", "dsp_tiles"):
			expected_col = getattr(expected_config, col_name)
			given_col = getattr(config, col_name)
			self.assertEqual(expected_col, given_col, f"Contents of {col_name} differ from expected values:")
	
	def test_get_bit(self):
		asc_path = self.get_data("send_all_bram.512x8.asc", must_exist=True)
		config = Configuration.create_from_asc(asc_path)
		
		data_path = self.get_data("send_all_bram.512x8.json", must_exist=True)
		with open(data_path, "r") as data_file:
			data = json.load(data_file)
		x, y = data[0]
		
		tile_data = data[1]
		
		for group in range(len(tile_data)):
			for index in range(len(tile_data[0])):
				res = config.get_bit(x, y, group, index)
				expected = tile_data[group][index]
				self.assertEqual(expected, res)
	
	def test_get_bits(self):
		asc_path = self.get_data("send_all_bram.512x8.asc", must_exist=True)
		config = Configuration.create_from_asc(asc_path)
		
		data_path = self.get_data("send_all_bram.512x8.json", must_exist=True)
		with open(data_path, "r") as data_file:
			data = json.load(data_file)
		tile_pos = TilePosition(*data[0])
		
		tile_data = tuple(data[1])
		
		# single bits
		for group in range(len(tile_data)):
			for index in range(len(tile_data[0])):
				bits = (Bit(group, index), )
				values = config.get_bits(tile_pos, bits)
				expected = (tile_data[group][index], )
				self.assertEqual(expected, values)
		
		# multiple bits
		for bits in ((Bit(3, 4), Bit(0, 0)), (Bit(8, 7), Bit(3, 22), Bit(2, 9), Bit(15, 38))):
			expected = tuple(tile_data[b.group][b.index] for b in bits)
			values = config.get_bits(tile_pos, bits)
			self.assertEqual(expected, values)
	
	def test_set_bit(self):
		test_data = (
			(0, 1, 7, 17, True),
			(25, 7, 7, 17, False),
			(15, 16, 15, 38, True)
		)
		
		config = Configuration.create_blank()
		
		for args in test_data:
			config.set_bit(*args)
			res = config.get_bit(*args[:-1])
			self.assertEqual(args[-1], res)
	
	def test_set_bits(self):
		test_data = (
			(TilePosition(0, 1), (Bit(7, 17), ), (True, )),
			(TilePosition(25, 7), (Bit(7, 17), Bit(8, 7)), (True, False)),
			(TilePosition(15, 16), (Bit(7, 17), Bit(3, 22), Bit(2, 9), Bit(15, 38)), (False, True, False, True)),
		)
		
		config = Configuration.create_blank()
		
		for tile_pos, bits, values in test_data:
			config.set_bits(tile_pos, bits, values)
			read = config.get_bits(tile_pos, bits)
			self.assertEqual(values, read)
	
	def test_get_bram_values(self):
		sbm = self.load_send_bram_meta()
		for current in sbm:
			with self.subTest(mode=current.mode):
				asc_path = self.get_data(current.asc_filename, must_exist=True)
				config = Configuration.create_from_asc(asc_path)
				
				# read single
				for address, expected in enumerate(current.initial_data):
					value = config.get_bram_values(current.ram_block, address, 1, current.mode)
					self.assertEqual(expected, value[0])
				
				# read all
				values = config.get_bram_values(current.ram_block, 0, len(current.initial_data), current.mode)
				self.assertEqual(current.initial_data, values)
			
	
	def test_set_bram_values(self):
		sbm = self.load_send_bram_meta()
		for current in sbm:
			with self.subTest(mode=current.mode):
				asc_path = self.get_data(current.asc_filename, must_exist=True)
				config = Configuration.create_from_asc(asc_path)
				
				expected = list(current.initial_data)
				# write single
				for address, old_value in enumerate(current.initial_data):
					new_value = current.mask ^ old_value
					config.set_bram_values(current.ram_block, [new_value], address, current.mode)
					expected[address] = new_value
					values = config.get_bram_values(current.ram_block, 0, len(current.initial_data), current.mode)
					self.assertEqual(expected, values)
				
				# write all
				config.set_bram_values(current.ram_block, current.initial_data, 0, current.mode)
				values = config.get_bram_values(current.ram_block, 0, len(current.initial_data), current.mode)
				self.assertEqual(current.initial_data, values)
		pass
	
	def test_asc_compare(self):
		# self test for the assert_structural_equal method
		
		echo_path = self.get_data("echo.asc", must_exist=True)
		send_path = self.get_data("send_all_bram.512x8.asc", must_exist=True)
		
		with open(echo_path, "r") as asc_file_a, open(echo_path, "r") as asc_file_b:
			self.assert_structural_equal(asc_file_a, asc_file_b)
		
		with open(echo_path, "r") as asc_file_a, open(send_path, "r") as asc_file_b:
			with self.assertRaises(AssertionError):
				self.assert_structural_equal(asc_file_a, asc_file_b)
		
	
	def test_read_opcodes(self):
		# test if the correct opcodes of a binar bitstream are identified
		exp = [
			(88, 0x51, 0x00),
			(90, 0x01, 0x05),
			(92, 0x92, 0x0020),
			(95, 0x62, 0x0367),
			(98, 0x72, 0x0110),
			(101, 0x82, 0x0000),
			(104, 0x11, 0x00),
			(106, 0x01, 0x01),
			(29758, 0x11, 0x01),
			(29760, 0x01, 0x01),
			(59412, 0x11, 0x02),
			(59414, 0x01, 0x01),
			(89066, 0x11, 0x03),
			(89068, 0x01, 0x01),
			(118720, 0x62, 0x007f),
			(118723, 0x72, 0x0080),
			(118726, 0x11, 0x00),
			(118728, 0x82, 0x0000),
			(118731, 0x01, 0x03),
			(120783, 0x82, 0x0080),
			(120786, 0x01, 0x03),
			(122838, 0x11, 0x01),
			(122840, 0x82, 0x0000),
			(122843, 0x01, 0x03),
			(124895, 0x82, 0x0080),
			(124898, 0x01, 0x03),
			(126950, 0x11, 0x02),
			(126952, 0x82, 0x0000),
			(126955, 0x01, 0x03),
			(129007, 0x82, 0x0080),
			(129010, 0x01, 0x03),
			(131062, 0x11, 0x03),
			(131064, 0x82, 0x0000),
			(131067, 0x01, 0x03),
			(133119, 0x82, 0x0080),
			(133122, 0x01, 0x03),
			(135174, 0x22, 0xb399),
			(135177, 0x01, 0x06),
		]
		# compare to known data
		bin_path = self.get_data("echo.bin", must_exist=True)
		
		dut = Configuration.create_blank()
		with open(bin_path, "rb") as bin_file:
			res = dut.read_opcodes(bin_file)
			self.assertEqual(exp, res)
	
	def assert_structural_equal(self, asc_file_a, asc_file_b):
		parts_a = self.load_asc_parts(asc_file_a)
		parts_b = self.load_asc_parts(asc_file_b)
		
		#self.assertEqual(parts_a, parts_b)
		self.assert_subset(parts_a, parts_b)
		self.assert_subset(parts_b, parts_a)
	
	def assert_subset(self, parts_a, parts_b):
		for entry in sorted(parts_a):
			if entry.name == ".ram_data" and all(all(s=="0" for s in r) for r in parts_a[entry]) and entry not in parts_b:
				continue
			self.assertIn(entry, parts_b)
			self.assertEqual(parts_a[entry], parts_b[entry])
		
	
	@staticmethod
	def load_asc_parts(asc_file):
		asc_dict = {}
		prev_data = None
		for line in asc_file:
			line = line.strip()
			#if line == "":
			#	continue
			if line[0] == ".":
				line_parts = line.split()
				entry = ASCEntry(line_parts[0], tuple(line_parts[1:]))
				assert entry not in asc_dict, f"multiple entries for {entry}"
				prev_data = []
				asc_dict[entry] = prev_data
			else:
				prev_data.append(line)
		
		return asc_dict
