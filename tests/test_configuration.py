#!/usr/bin/env python3
import json
import os
import random
import sys
import time
import unittest

from contextlib import ExitStack
from dataclasses import dataclass
from io import BytesIO
from itertools import combinations
from typing import NamedTuple, List

import numpy as np

from ..configuration import BinOpt, Configuration
from ..device_data import TilePosition, BRAMMode, Bit
from ..fpga_board import FPGABoard

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
	
	def test_create_from_asc_filename(self):
		asc_path = self.get_data("send_all_bram.512x8.asc", must_exist=True)
		config = Configuration.create_from_asc_filename(asc_path)
		
		# check logic cell
		data_path = self.get_data("send_all_bram.512x8.json", must_exist=True)
		with open(data_path, "r") as data_file:
			data = json.load(data_file)
		tile_pos = TilePosition(*data[0])
		
		tile_data = np.array(data[1])
		
		np.testing.assert_equal(tile_data, config._tiles[tile_pos])
		
		# check bram
		bram_pos = TilePosition(*data[2])
		bram_data = np.array(data[3])
		
		np.testing.assert_equal(bram_data, config._bram[bram_pos][:len(bram_data)])
		rest = np.full((len(config._bram[bram_pos])-len(bram_data), len(bram_data[0])), False)
		np.testing.assert_equal(rest, config._bram[bram_pos][len(bram_data):])
	
	def test_create_from_asc(self):
		asc_path = self.get_data("send_all_bram.512x8.asc", must_exist=True)
		with open(asc_path, "r") as asc_file:
			config = Configuration.create_from_asc(asc_file)
		
		# check logic cell
		data_path = self.get_data("send_all_bram.512x8.json", must_exist=True)
		with open(data_path, "r") as data_file:
			data = json.load(data_file)
		tile_pos = TilePosition(*data[0])
		
		tile_data = np.array(data[1])
		
		np.testing.assert_equal(tile_data, config._tiles[tile_pos])
		
		# check bram
		bram_pos = TilePosition(*data[2])
		bram_data = np.array(data[3])
		
		np.testing.assert_equal(bram_data, config._bram[bram_pos][:len(bram_data)])
		rest = np.full((len(config._bram[bram_pos])-len(bram_data), len(bram_data[0])), False)
		np.testing.assert_equal(rest, config._bram[bram_pos][len(bram_data):])
	
	def test_write_asc(self):
		asc_path = self.get_data("send_all_bram.512x8.asc", must_exist=True)
		config = Configuration.create_from_asc_filename(asc_path)
		
		with open(asc_path, "r") as org, open("tmp.test_write_asc.asc", "w+") as res:
			config.write_asc(res)
			res.seek(0)
			self.assert_structural_equal(org, res)
	
	@unittest.skipUnless(load_icebox(), "icebox unavailable")
	def test_write_asc_icestorm(self):
		# test writing asc based on iceconfig
		import icebox
		
		asc_path = self.get_data("send_all_bram.512x8.asc", must_exist=True)
		config = Configuration.create_from_asc_filename(asc_path)
		
		expected_ic = icebox.iceconfig()
		expected_ic.read_file(asc_path)
		
		out_path = "tmp.test_write_asc.asc"
		with open(out_path, "w") as res:
			config.write_asc(res)
		
		res_ic = icebox.iceconfig()
		res_ic.read_file(out_path)
		
		self.check_iceconfig(expected_ic, res_ic)
		
		os.remove(out_path)
	
	def check_iceconfig(self, expected_config, config):
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
	
	def check_configuration(self, exp_config, config, check_bram=True, check_cram=True, check_comment=True):
		# assert two Configuration instances are equal
		to_check = ["_freq_range", "_warmboot", "_nosleep", ]
		if check_bram:
			to_check.append("_bram")
		if check_cram:
			to_check.append("_tiles")
			to_check.append("_extra_bits")
		if check_comment:
			to_check.append("_comment")
		
		for var_name in to_check:
			exp_value = getattr(exp_config, var_name)
			value = getattr(config, var_name)
			np.testing.assert_equal(exp_value, value, f"Contents of {var_name} differ from expected values:")
	
	def test_get_bit(self):
		asc_path = self.get_data("send_all_bram.512x8.asc", must_exist=True)
		config = Configuration.create_from_asc_filename(asc_path)
		
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
		config = Configuration.create_from_asc_filename(asc_path)
		
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
				config = Configuration.create_from_asc_filename(asc_path)
				
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
				config = Configuration.create_from_asc_filename(asc_path)
				
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
	
	def test_asc_compare(self):
		# self test for the assert_structural_equal method
		
		echo_path = self.get_data("echo.asc", must_exist=True)
		send_path = self.get_data("send_all_bram.512x8.asc", must_exist=True)
		
		with open(echo_path, "r") as asc_file_a, open(echo_path, "r") as asc_file_b:
			self.assert_structural_equal(asc_file_a, asc_file_b)
		
		with open(echo_path, "r") as asc_file_a, open(send_path, "r") as asc_file_b:
			with self.assertRaises(AssertionError):
				self.assert_structural_equal(asc_file_a, asc_file_b)
		
	
	def generic_read_bin_test(self, base_name):
		bin_path = self.get_data(f"{base_name}.bin", must_exist=True)
		out_filename = f"tmp.generic_read_bin_test.{base_name}.asc"
		
		dut = Configuration.create_blank()
		with open(bin_path, "rb") as bin_file:
			dut.read_bin(bin_file)
		
		data_path = self.get_data(f"{base_name}.json", must_exist=True)
		with open(data_path, "r") as data_file:
			data = json.load(data_file)
		
		# check logic cell
		tile_pos = TilePosition(*data[0])
		tile_data = np.array(data[1])
		
		with open(out_filename, "w") as asc_out:
			dut.write_asc(asc_out)
		
		np.testing.assert_equal(dut._tiles[tile_pos], tile_data)
		
		# check bram
		bram_pos = TilePosition(*data[2])
		bram_data = np.array(data[3])
		
		np.testing.assert_equal(dut._bram[bram_pos][:len(bram_data)], bram_data)
		rest = np.full((len(dut._bram[bram_pos])-len(bram_data), len(bram_data[0])), False)
		np.testing.assert_equal(dut._bram[bram_pos][len(bram_data):], rest)
		
		os.remove(out_filename)
	
	def test_read_bin_known_bits(self):
		for base_name in ["send_all_bram.512x8", "send_all_bram.256x16.25_27"]:
			with self.subTest(base_name=base_name):
				self.generic_read_bin_test(base_name)
	
	def test_read_bin_pairs(self):
		for bin_file, asc_file in self.iter_bin_asc_pairs():
			with self.subTest(asc_name=os.path.basename(asc_file.name)):
				dut = Configuration.create_blank()
				
				# read bin
				dut.read_bin(bin_file)
				
				# write asc
				out_filename = f"tmp.test_read_bin_asc.{os.path.basename(bin_file.name)}.asc"
				with open(out_filename, "w") as out_file:
					dut. write_asc(out_file)
				
				# compare asc
				with open(out_filename, "r") as res_file:
					self.assert_structural_equal(asc_file, res_file)
				
				# read ref asc
				asc_file.seek(0)
				exp_config = Configuration.create_blank()
				exp_config.read_asc(asc_file)
				
				# compare configurations
				self.check_configuration(exp_config, dut)
				
				# clean up
				os.remove(out_filename)
	
	def test_read_no_header(self):
		# read bitstream without comment field
		dut = Configuration.create_blank()
		
		bin_path = self.get_data("smallest.bin", must_exist=True)
		
		with open(bin_path, "rb") as bin_file:
			dut.read_bin(bin_file)
			
			exp_config = Configuration.create_blank()
			
			self.check_configuration(exp_config, dut)
	
	@unittest.skipIf(len(FPGABoard.get_suitable_serial_numbers())<1, "no suitable boards found")
	def test_flash_empty(self):
		bin_path = self.get_data("smallest.bin", must_exist=True)
		with open(bin_path, "rb") as tmp_file:
			bitstream = tmp_file.read()
		
		with FPGABoard.get_suitable_board() as fpga:
			fpga.flash_bitstream(bitstream)
	
	def test_get_bitstream(self):
		for bin_file, asc_file in self.iter_bin_asc_pairs():
			with self.subTest(asc_name=asc_file.name):
				dut = Configuration.create_blank()
				dut.read_asc(asc_file)
				
				res = dut.get_bitstream()
				
				exp = bin_file.read()
				
				self.assertEqual(exp, res)
	
	def test_write_bin_asc(self):
		for asc_file in self.iter_asc_files():
			with self.subTest(asc_name=asc_file.name):
				out_filename = f"tmp.test_write_bin_asc.{os.path.basename(asc_file.name)}.bin"
				
				exp = Configuration.create_blank()
				dut = Configuration.create_blank()
				res = Configuration.create_blank()
				
				exp.read_asc(asc_file)
				asc_file.seek(0)
				dut.read_asc(asc_file)
				
				with open(out_filename, "wb") as out_file:
					dut.write_bin(out_file)
				
				with open(out_filename, "rb") as out_file:
					res.read_bin(out_file)
				
				self.check_configuration(exp, res)
				
				os.remove(out_filename)
	
	def test_write_bin_pairs(self):
		for bin_file, asc_file in self.iter_bin_asc_pairs():
			with self.subTest(asc_name=asc_file.name):
				out_filename = f"tmp.test_write_bin_pairs.{os.path.basename(bin_file.name)}"
				dut = Configuration.create_blank()
				dut.read_asc(asc_file)
				
				with open(out_filename, "wb") as out_file:
					dut.write_bin(out_file)
				
				exp = bin_file.read()
				with open(out_filename, "rb") as out_file:
					res = out_file.read()
				
				self.assertEqual(exp, res)
				
				os.remove(out_filename)
	
	def iter_bin_asc_pairs(self):
		pairs = [
			("echo.bin", "echo.asc"),
			("send_all_bram.256x16.25_27.bin", "send_all_bram.256x16.25_27.asc"),
			("read_bram_random.bin", "read_bram_random.asc"),
		]
		
		for bin_filename, asc_filename in pairs:
			bin_path = self.get_data(bin_filename, must_exist=True)
			asc_path = self.get_data(asc_filename, must_exist=True)
			
			with open(bin_path, "rb") as bin_file, open(asc_path, "r") as asc_file:
				yield bin_file, asc_file 
	
	def iter_asc_files(self):
		for asc_filename in [
			"send_all_bram.256x16.25_27.asc", "send_all_bram.256x16.asc", "send_all_bram.512x8.asc", 
			"send_all_bram.1024x4.asc", "send_all_bram.2048x2.asc", "echo.asc", "read_bram_random.asc",
		]:
			path = self.get_data(asc_filename, must_exist=True)
			with open(path, "r") as asc_file:
				yield asc_file
	
	def test_skip_bram(self):
		for bin_file, asc_file in self.iter_bin_asc_pairs():
			with self.subTest(asc_name=os.path.basename(asc_file.name)):
				out_filename = f"tmp.test_skip_bram.{os.path.basename(bin_file.name)}"
				
				exp = Configuration.create_blank()
				exp.read_asc(asc_file)
				for tile_pos in exp._bram:
					exp.set_bram_values(tile_pos, [0]*256, 0, BRAMMode.BRAM_256x16)
				
				dut = Configuration.create_blank()
				dut.read_bin(bin_file)
				with open(out_filename, "wb") as out_file:
					dut.write_bin(out_file, BinOpt(detect_used_bram=False, bram_banks=[]))
				
				res = Configuration.create_blank()
				with open(out_filename, "rb") as out_file:
					res.read_bin(out_file)
				
				self.check_configuration(exp, res)
				
				os.remove(out_filename)
	
	def test_skip_unused_bram(self):
		test_data = [
			("echo.bin", "echo.asc", []),
			("send_all_bram.256x16.25_27.bin", "send_all_bram.256x16.25_27.asc", [3]),
			("read_bram_random.bin", "read_bram_random.asc", [0, 1, 2, 3]),
		]
		
		mode = BRAMMode.BRAM_512x8
		val_count = Configuration.block_size_from_mode(mode)
		max_val = 1 << Configuration.value_length_from_mode(mode) - 1
		for bin_filename, asc_filename, bank_numbers in test_data:
			with ExitStack() as stack:
				stack.enter_context(self.subTest(asc_name=os.path.basename(asc_filename)))
				bin_path = self.get_data(bin_filename, must_exist=True)
				bin_file = stack.enter_context(open(bin_path, "rb"))
				asc_path = self.get_data(asc_filename, must_exist=True)
				asc_file = stack.enter_context(open(asc_path, "r"))
				
				out_filename = f"tmp.test_skip_unused_bram.{os.path.basename(bin_file.name)}"
				
				exp = Configuration.create_blank()
				exp.read_asc(asc_file)
				
				dut = Configuration.create_blank()
				dut.read_bin(bin_file)
				# write known values
				bram_list = list(dut._bram.keys())
				new_data = {p: [random.randint(0, max_val) for _ in range(val_count)] for p in bram_list}
				for pos, data in new_data.items():
					dut.set_bram_values(pos, data, 0, mode)
					
					cur_bank = 2*(pos.x > 16) + (pos.y > 16)
					if cur_bank in bank_numbers:
						exp.set_bram_values(pos, data, 0, mode)
				
				with open(out_filename, "wb") as out_file:
					dut.write_bin(out_file, BinOpt(detect_used_bram=True))
				
				res = Configuration.create_blank()
				with open(out_filename, "rb") as out_file:
					res.read_bin(out_file)
				
				#print(f"{os.path.basename(bin_file.name)}: {os.path.getsize(bin_file.name)} -> {os.path.getsize(out_filename)}")
				self.check_configuration(exp, res)
				
				os.remove(out_filename)
	
	def test_skip_comment(self):
		for bin_file, asc_file in self.iter_bin_asc_pairs():
			with self.subTest(asc_name=os.path.basename(asc_file.name)):
				out_filename = f"tmp.test_skip_comment.{os.path.basename(bin_file.name)}"
				
				exp = Configuration.create_blank()
				exp.read_asc(asc_file)
				exp._comment = ""
				
				dut = Configuration.create_blank()
				dut.read_bin(bin_file)
				with open(out_filename, "wb") as out_file:
					dut.write_bin(out_file, BinOpt(skip_comment=True))
				
				res = Configuration.create_blank()
				with open(out_filename, "rb") as out_file:
					res.read_bin(out_file)
				
				#print(f"{os.path.basename(bin_file.name)}: {os.path.getsize(bin_file.name)} -> {os.path.getsize(out_filename)}")
				self.check_configuration(exp, res)
				
				os.remove(out_filename)
	
	def test_optimize(self):
		prev = {}
		for opt_lvl in range(5):
			with self.subTest(opt_lvl=opt_lvl):
				#print(f"opt level: {opt_lvl}")
				for bin_file, asc_file in self.iter_bin_asc_pairs():
					out_filename = f"tmp.test_optimization.{os.path.basename(bin_file.name)}"
					dut = Configuration.create_blank()
					dut.read_bin(bin_file)
					with open(out_filename, "wb") as out_file:
						dut.write_bin(out_file, BinOpt(optimize = opt_lvl))
					
					new_size = os.path.getsize(out_filename)
					try:
						self.assertGreaterEqual(prev[out_filename], new_size)
						#print(prev[out_filename], new_size)
					except KeyError:
						pass
					prev[out_filename] = new_size
					#print(f"{os.path.basename(bin_file.name)}: {os.path.getsize(bin_file.name)} -> {new_size}")
					
					exp = Configuration.create_blank()
					exp.read_asc(asc_file)
					
					res = Configuration.create_blank()
					with open(out_filename, "rb") as out_file:
						res.read_bin(out_file)
					
					self.check_configuration(exp, res)
					
					os.remove(out_filename)
		
	@unittest.skipIf(len(FPGABoard.get_suitable_serial_numbers())<1, "no suitable boards found")
	def test_options_with_hardware(self):
		path = self.get_data("read_bram_random.bin", must_exist=True)
		test_cases = [
			("default", BinOpt()),
			("smallest", BinOpt(skip_comment=True, detect_used_bram=False, bram_banks=[], optimize=4)),
		]
		for desc, bin_opt in test_cases:
			with self.subTest(desc=desc):
				dut = Configuration.create_blank()
				with open(path, "rb") as bin_file:
					dut.read_bin(bin_file)
				
				with BytesIO() as tmp_file:
					dut.write_bin(tmp_file, bin_opt)
					bitstream = tmp_file.getvalue()
				#print(f"{os.path.getsize(path)} -> {len(bitstream)}")
				
				with FPGABoard.get_suitable_board() as fpga:
					fpga.flash_bitstream(bitstream)
					for i, tile in enumerate(sorted(dut._bram)):
						fpga.uart.write(i.to_bytes(1, "little"))
						val = fpga.read_integers(256, data_width=2)
						exp = dut.get_bram_values(tile, 0, 256, BRAMMode.BRAM_256x16)
						self.assertEqual(exp, val)
	
	@unittest.skipIf(len(FPGABoard.get_suitable_serial_numbers())<1, "no suitable boards found")
	def test_bram_with_hardware(self):
		# fill BRAM with known values, overwrite part of the BRAM and read back whole BRAM to check iff the overwriten
		# values changed
		prev_conf = Configuration.create_blank()
		
		bin_path = self.get_data("read_bram_random.bin", must_exist=True)
		with open(bin_path, "rb") as bin_file:
			send_conf = Configuration.create_blank()
			send_conf.read_bin(bin_file)
		mode = BRAMMode.BRAM_256x16
		val_count = Configuration.block_size_from_mode(mode)
		max_val = 1 << Configuration.value_length_from_mode(mode) - 1
		bram_list = list(send_conf._bram.keys())
		
		bank_indices = list(range(4))
		for bank_numbers in [c for l in range(len(bank_indices)+1) for c in combinations(bank_indices, l)]:
			with self.subTest(bank_numbers=bank_numbers):
				prev_data = {p: [random.randint(0, max_val) for _ in range(val_count)] for p in bram_list}
				new_data = {p: [random.randint(0, max_val) for _ in range(val_count)] for p in bram_list}
				
				for pos, data in prev_data.items():
					prev_conf.set_bram_values(pos, data, 0, mode)
				for pos, data in new_data.items():
					send_conf.set_bram_values(pos, data, 0, mode)
				
				
				with FPGABoard.get_suitable_board() as fpga:
					# write previous BRAM values
					fpga.configure(prev_conf, BinOpt(detect_used_bram=False, bram_banks=None)) # None == no restriction
					
					# write send bitstream and the new BRAM values
					fpga.configure(send_conf, BinOpt(detect_used_bram=False, bram_banks=bank_numbers))
					
					for i, pos in enumerate(sorted(bram_list)):
						cur_bank = 2*(pos.x > 16) + (pos.y > 16)
						fpga.uart.write(i.to_bytes(1, "little"))
						res = fpga.read_integers(val_count, data_width=2)
						
						if cur_bank in bank_numbers:
							self.assertEqual(new_data[pos], res)
						else:
							self.assertEqual(prev_data[pos], res)
	
	def test_access_bram_matching(self):
		# test that reading and writing BRAM banks go together
		for asc_file in self.iter_asc_files():
			with self.subTest(asc_name=asc_file.name):
				dut1 = Configuration.create_blank()
				dut2 = Configuration.create_blank()
				
				dut1.read_asc(asc_file)
				
				bram = dut1._all_blank_bram_banks()
				dut1._write_bram_banks(bram)
				dut2._read_bram_banks(bram)
				
				self.assertEqual(dut1._bram.keys(), dut2._bram.keys())
				for tile, data in dut1._bram.items():
					np.testing.assert_equal(data, dut2._bram[tile], f"Difference in RAM data at {tile}")
	
	def test_access_cram_matching(self):
		# test that reading and writing CRAM banks go together
		for asc_file in self.iter_asc_files():
			with self.subTest(asc_name=asc_file.name):
				dut1 = Configuration.create_blank()
				dut2 = Configuration.create_blank()
				
				dut1.read_asc(asc_file)
				
				cram = dut1._all_blank_cram_banks()
				dut1._write_cram_banks(cram)
				dut2._read_cram_banks(cram)
				
				self.assertEqual(dut1._tiles.keys(), dut2._tiles.keys())
				for tile, data in dut1._tiles.items():
					np.testing.assert_equal(data, dut2._tiles[tile], f"Difference in tile data at {tile}")
				
				self.assertEqual(dut1._extra_bits, dut2._extra_bits)
	
	def test_reverse_slice(self):
		for l in range(5):
			to_slice = list(range(l))
			for start in range(-l, 2*l):
				for stop in range(-l, 2*l):
					org_slice = slice(start, stop, 1)
					
					rev_slice = Configuration.reverse_slice(org_slice)
					exp = list(reversed(to_slice[org_slice]))
					res = to_slice[rev_slice]
					
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
			self.assertIn(entry, parts_b.keys())
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
