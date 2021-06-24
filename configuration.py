#!/usr/bin/env python3

import binascii
import os
from array import array
import timeit
import enum

from io import BytesIO
from itertools import zip_longest
from typing import Any, BinaryIO, Iterable, List, NamedTuple, NewType, Sequence, TextIO, Tuple

import numpy as np

from .device_data import Bit, BRAMMode, DeviceSpec, ExtraBit, TilePosition, TileType, SPECS_BY_ASC

Banks = NewType("Banks", np.ndarray)

class FreqRange(enum.IntEnum):
	"""Values for internal oscillator frequncy range
	
	Relevant for configuration in SPI master mode.
	Depends on thr PROM speed.
	"""
	LOW = 0
	MEDIUM = 1
	HIGH = 2

class MalformedBitstreamError(Exception):
	"""Raised when an not incorrect bitstream is encountered."""
	pass

class CRC:
	def __init__(self) -> None:
		self.reset()
	
	@property
	def value(self) -> int:
		return self._value
	
	def reset(self) -> None:
		self._value = 0xFFFF
	
	def update(self, data: bytes) -> None:
		self._value = binascii.crc_hqx(data, self._value)

NOSLEEP_MASK = 1
WARMBOOT_MASK = 1<<5

class BinOut:
	"""Wrapper around BinaryIO to provide functions for creating binary bitstreams"""
	
	BOOLS_TO_BYTES = {tuple(v&1<<(7-i) != 0 for i in range(8)): v for v in range(256)}
	
	def __init__(self, bin_file: BinaryIO) -> None:
		self._bin_file = bin_file
		self._crc = CRC()
		self._bank_number = None
		self._bank_width = None
		self._bank_height = None
		self._bank_offset = None
		
	
	def write_bytes(self, data: bytes) -> None:
		"""Write bytes, update CRC accordingly"""
		count = self._bin_file.write(data)
		
		if count != len(data):
			raise IOError(f"only {count} of {len(data)} bytes written")
		
		self._crc.update(data)
	
	def write_comment(self, comment: str) -> None:
		self.write_bytes(b"\xff\x00")
		
		if comment:
			if comment[-1] == "\n":
				comment = comment[:-1]
			for line in comment.split("\n"):
				self.write_bytes(line.encode("utf-8"))
				self.write_bytes(b"\x00")
		
		self.write_bytes(b"\x00\xff")
	
	def write_preamble(self) -> None:
		self.write_bytes(b"\x7e\xaa\x99\x7e")
	
	def write_freq_range(self, freq_range: FreqRange) -> None:
		self.write_bytes(b"\x51")
		self.write_bytes(bytes([int(freq_range)]))
	
	def crc_reset(self) -> None:
		self.write_bytes(b"\x01\x05")
		self._crc.reset()
	
	def write_warmboot(self, warmboot: bool, nosleep: bool) -> None:
		"""Write warmboot and nosleep flags"""
		self.write_bytes(b"\x92\x00")
		wn = 0
		if nosleep:
			wn |= NOSLEEP_MASK
		if warmboot:
			wn |= WARMBOOT_MASK
		self.write_bytes(bytes([wn]))
	
	def set_bank_number(self, number: int) -> None:
		self.write_bytes(b"\x11")
		self.write_bytes(bytes([number]))
		self._bank_number = number
	
	def set_bank_width(self, width: int) -> None:
		self.write_bytes(b"\x62")
		self.write_bytes((width-1).to_bytes(2, "big"))
		self._bank_width = width
	
	def set_bank_height(self, height: int) -> None:
		self.write_bytes(b"\x72")
		self.write_bytes(height.to_bytes(2, "big"))
		self._bank_height = height
	
	def set_bank_offset(self, offset: int) -> None:
		self.write_bytes(b"\x82")
		self.write_bytes(offset.to_bytes(2, "big"))
		self._bank_offset = offset
	
	def data_from_xram(self, xram: Banks) -> bytes:
		return np.packbits(xram[self._bank_number, self._bank_offset:self._bank_offset+self._bank_height, :self._bank_width], bitorder="big").tobytes()
	
	def write_cram(self, cram: Banks) -> None:
		data = self.data_from_xram(cram)
		self.write_bytes(b"\x01\x01")
		self.write_bytes(data)
		self.write_bytes(b"\x00\x00")
	
	def write_bram(self, bram: Banks) -> None:
		data = self.data_from_xram(bram)
		self.write_bytes(b"\x01\x03")
		self.write_bytes(data)
		self.write_bytes(b"\x00\x00")
	
	def crc_check(self) -> None:
		self.write_bytes(b"\x22")
		self.write_bytes(self._crc.value.to_bytes(2, "big"))
	
	def wakeup(self) -> None:
		self.write_bytes(b"\x01\x06")
	

TILE_TYPE_TO_ASC_ENTRY = {
	TileType.LOGIC: "logic_tile",
	TileType.IO: "io_tile",
	TileType.RAM_T: "ramt_tile",
	TileType.RAM_B: "ramb_tile",
}

ASC_ENTRY_TO_TILE_TYPE = {a:t for t, a in TILE_TYPE_TO_ASC_ENTRY.items()}

class Configuration:
	"""represents the configuration of a FPGA"""
	
	def __init__(self, device_spec: DeviceSpec) -> None:
		self._spec = device_spec
		self.clear()
	
	def clear(self) -> None:
		self._bram = {}
		self._tiles = {}
		self._tiles_by_type = {}
		self._tile_types = {}
		self._comment = ""
		self._freq_range = FreqRange.LOW
		self._warmboot = True
		self._nosleep = False
		self._extra_bits = []
		
		for pos, ttype in self._spec.get_tile_types():
			width = self._spec.tile_type_width[ttype]
			height = self._spec.tile_height
			data = np.full((height, width), False, dtype=bool)
			self._tiles[pos] = data
			self._tiles_by_type.setdefault(ttype, []).append(pos)
			self._tile_types[pos] = ttype
			
			if ttype == TileType.RAM_B:
				self._bram[pos] = np.full((16, 256), False, dtype=bool)
		
	
	def get_bit(self, x: int, y: int, group: int, index: int) -> bool:
		return self._tiles[(x, y)][group, index]
	
	def get_bits(self, tile: TilePosition, bits: Iterable[Bit]) -> Tuple[bool, ...]:
		tile_data = self._tiles[tile]
		values = [tile_data[b.group, b.index] for b in bits]
		
		return tuple(values)
	
	def set_bit(self, x: int, y: int, group: int, index: int, value: bool) -> None:
		self._tiles[(x, y)][group, index] = value
	
	def set_bits(self, tile: TilePosition, bits: Iterable[Bit], values: Iterable[bool]) -> None:
		tile_data = self._tiles[tile]
		for i, b in enumerate(bits):
			tile_data[b.group, b.index] = values[i]
	
	@classmethod
	def block_size_from_mode(cls, mode: BRAMMode) -> int:
		return 4096//cls.value_length_from_mode(mode)
	
	@staticmethod
	def value_length_from_mode(mode: BRAMMode) -> int:
		return 16 >> mode.value
	
	@staticmethod
	def split_bram_address(address: int) -> Tuple[int, int, int]:
		index = address % 256
		offset = address // 256
		col_index = index % 16
		row_index = index // 16
		
		return row_index, col_index, offset
	
	@classmethod
	def get_from_bram_data(cls, bram_data: np.ndarray, address: int, mode: BRAMMode=BRAMMode.BRAM_512x8) -> int:
		# bram_data ndarray(shape=(16, 256), dtype=bool)
		value_len = cls.value_length_from_mode(mode)
		row_index, col_index, offset = cls.split_bram_address(address)
		
		row_data = bram_data[row_index]
		index = col_index * 16 + offset
		step = 16 // value_len
		value = 0
		for i in range(value_len):
			value |= row_data[index] << i
			index += step
		
		return value
	
	@classmethod
	def set_in_bram_data(cls, bram_data: np.ndarray, address: int, value: int, mode: BRAMMode=BRAMMode.BRAM_512x8) -> None:
		# bram_data ndarray(shape=(16, 256), dtype=bool)
		value_len = cls.value_length_from_mode(mode)
		row_index, col_index, offset = cls.split_bram_address(address)
		
		assert value >= 0, "Value has to be non negative."
		assert value < pow(2, value_len), f"Value {value} too large for bit length {value_len}."
		
		row_data = bram_data[row_index]
		index = col_index * 16 + offset
		step = 16 // value_len
		for i in range(value_len):
			row_data[index] = ((value >> i) & 1) == 1
			index += step
		
	
	def get_bram_values(self, ram_block: TilePosition, address: int=0, count: int=1, mode: BRAMMode=BRAMMode.BRAM_512x8) -> List[int]:
		bram_data =self._bram[ram_block]
		values = []
		for tmp_address in range(address, address+count):
			value = self.get_from_bram_data(bram_data, tmp_address, mode)
			values.append(value)
		
		return values
	
	def set_bram_values(self, ram_block: TilePosition, values: Iterable[int], address: int=0, mode: BRAMMode=BRAMMode.BRAM_512x8) -> None:
		ram_data = self._bram[ram_block]
		for value in values:
			self.set_in_bram_data(ram_data, address, value, mode)
			address += 1
	
	def read_asc(self, asc_file: TextIO) -> None:
		ASCState = enum.Enum("ASCState", ["READ_LINE", "FIND_ENTRY", "READ_TO_NEXT"])
		state = ASCState.READ_LINE
		comment_data = []
		current_data = None
		self.clear()
		while True:
			if state == ASCState.READ_LINE:
				try:
					line = self.get_line(asc_file)
				except EOFError:
					break
				
				state = ASCState.FIND_ENTRY
			elif state == ASCState.FIND_ENTRY:
				# default next state
				state = ASCState.READ_LINE
				
				line = line.strip()
				if line == "":
					continue
				
				if line[0] != ".":
					raise ValueError(f"expected start of entry, found '{line[:40]}' instead")
				
				parts = line.split()
				
				entry = parts[0][1:]
				if entry in ASC_ENTRY_TO_TILE_TYPE:
					current_data = self._tiles[(int(parts[1]), int(parts[2]))]
					for row in range(16):
						line = self.get_line(asc_file).strip()
						for col in range(len(current_data[row])):
							current_data[row][col] = (line[col] == "1")
				elif entry == "ram_data":
					ram_data = self._bram[(int(parts[1]), int(parts[2]))]
					for row in range(16):
						line = self.get_line(asc_file).strip()
						ram_index = 0
						for str_index in range(63, -1, -1):
							val = int(line[str_index], 16)
							for _ in range(4):
								ram_data[row][ram_index] = ((val & 1) == 1)
								val >>= 1
								ram_index += 1
				elif entry == "extra_bit":
					extra_bit = ExtraBit(int(parts[1]), int(parts[2]), int(parts[3]))
					self._extra_bits.append(extra_bit)
				elif entry == "comment":
					current_data = comment_data
					state = ASCState.READ_TO_NEXT
				elif entry == "device":
					if self._spec.asc_name != parts[1]:
						raise ValueError(f"asc for {parts[1]}, not {self._spec.asc_name}")
				elif entry == "warmboot":
					assert part[1] in ("enabled", "disabled")
					self._warmboot = (part[1] == "enabled")
				elif entry == "sym":
					# ignore symbols
					pass
				else:
					raise ValueError(f"unknown entry '{entry}'")
			elif state == ASCState.READ_TO_NEXT:
				try:
					line = self.get_line(asc_file)
				except EOFError:
					break
				
				# check if entry
				# fails if a comment line starts with '.'
				entry_line = line.lstrip()
				try:
					if entry_line[0] == ".":
						state = ASCState.FIND_ENTRY
						continue
				except IndexError:
					pass
				
				current_data.append(line)
		
		self._comment = "".join(comment_data)
	
	def write_asc(self, asc_file: TextIO) -> None:
		if self._comment != "":
			asc_file.write(".comment\n")
			asc_file.write(self._comment)
			if self._comment[-1] != "\n":
				asc_file.write("\n")
		
		asc_file.write(f".device {self._spec.asc_name }\n")
		
		if not self._warmboot:
			asc_file.write(f".warmboot disabled\n")
		
		for pos in sorted(self._tiles):
			tile_type = self._tile_types[pos]
			data = self._tiles[pos]
			
			asc_file.write(f".{TILE_TYPE_TO_ASC_ENTRY[tile_type]} {pos.x} {pos.y}\n")
			for row in data:
				asc_file.write("".join(["1" if b else "0" for b in row]))
				asc_file.write("\n")
		
		for pos in sorted(self._bram):
			data = self._bram[pos]
			if not any(any(r) for r in data):
				continue
			
			asc_file.write(f".ram_data {pos.x} {pos.y}\n")
			for row in data:
				str_list = []
				for i in range(len(row)//4):
					val = row[4*i+3] << 3 | row[4*i+2] << 2 | row[4*i+1] << 1 | row[4*i]
					str_list.append(f"{val:x}")
				asc_file.write("".join(str_list[::-1]))
				asc_file.write("\n")
		
		for extra_bit in self._extra_bits:
			asc_file.write(f".extra_bit {extra_bit.bank} {extra_bit.x} {extra_bit.y}\n")
	
	def _all_blank_cram_banks(self) -> Banks:
		"""Create all CRAM banks as used in binary bitstreams with all bits set to 0.
		
		Attention: the access to the bank b at x, y is reached by banks[b][y][x] to easier group the bits in the
		x dimension.
		"""
		return np.full((4, self._spec.cram_height, self._spec.cram_width), False, dtype=bool)
	
	def _all_blank_bram_banks(self) -> Banks:
		"""Create all BRAM banks as used in binary bitstreams with all bits set to 0.
		
		Attention: the access to the bank b at x, y is reached by banks[b][y][x] to easier group the bits in the
		x dimension.
		"""
		return np.full((4, self._spec.bram_height, self._spec.bram_width), False, dtype=bool)
	
	def read_bin(self, bin_file: BinaryIO):
		crc = CRC()
		self.expect_bytes(bin_file, b"\xff\x00", crc, "Didn't start with {exp}, but {val}")
		
		# read multiple null terminated comment
		com_list = []
		prv = b"\x00" # from 0xFF00
		cur = self.get_bytes_crc(bin_file, 1, crc)
		while True:
			while cur != b"\x00":
				com_list.append(cur)
				prv = cur
				cur = self.get_bytes_crc(bin_file, 1, crc)
			
			nxt = self.get_bytes_crc(bin_file, 1, crc)
			if nxt == b"\xff":
				if prv == b"\x00":
					# previous string null terminated and received 0x00FF
					# -> normal end of comment
					break
				else:
					# previous string not null terminated
					# -> Lattice bug that shifts 0x00FF some bytes into comments
					com_list.append(b"\n")
					break
			else:
				# another comment string
				prv = cur
				cur = nxt
			com_list.append(b"\n")
		
		self._comment = b"".join(com_list).decode("utf-8")
		
		# as Lattice' own tools create faulty comments just search for preamble instead of expecting it
		last_four = [None]*4
		while last_four != [b"\x7e", b"\xaa", b"\x99", b"\x7e"]:
			last_four = last_four[1:]
			last_four.append(self.get_bytes_crc(bin_file, 1, crc))
		
		bank_nr = None
		bank_width = None
		bank_height = None
		bank_offset = None
		
		def get_data_len():
			try:
				return bank_width*bank_height//8
			except TypeError as te:
				raise MalformedBitstreamError("Block height and width have to be set before writig data") from te
		
		def data_to_xram(data, xram):
			for y in range(bank_height):
				# msb first
				bit_data = [
					(b<<i) & 0x80 != 0 for b in data[y*bank_width//8:(y+1)*bank_width//8] for i in range(8)
				]
				xram[bank_nr][y+bank_offset][0:bank_width] = bit_data
			
		
		cram = self._all_blank_cram_banks()
		bram = self._all_blank_bram_banks()
		while True:
			file_offset = bin_file.tell()
			# don't use get_bytes as the end of the file should be detected here
			raw_com = bin_file.read(1)
			if len(raw_com) == 0:
				# end of file
				break
			crc.update(raw_com)
			
			command = raw_com[0]
			opcode = command >> 4
			payload_len = command & 0xf
			
			payload_bytes = self.get_bytes_crc(bin_file, payload_len, crc)
			payload = 0
			for val in payload_bytes:
				payload = payload << 8 | val
			
			if opcode == 0:
				if payload == 1:
					data_len = get_data_len()
					data = self.get_bytes_crc(bin_file, data_len, crc)
					data_to_xram(data, cram)
					self.expect_bytes(bin_file, b"\x00\x00", crc, "Expected 0x{exp:04x} after CRAM data, got 0x{val:04x}")
				elif payload == 3:
					data_len = get_data_len()
					data = self.get_bytes_crc(bin_file, data_len, crc)
					data_to_xram(data, bram)
					self.expect_bytes(bin_file, b"\x00\x00", crc, "Expected 0x{exp:04x} after BRAM data, got 0x{val:04x}")
				elif payload == 5:
					crc.reset()
				elif payload == 6:
					# wakeup -> ignore everything after that
					break
				else:
					# payload 8 (reboot) not supported
					raise MalformedBitstreamError(f"Unsupported Command: 0x{command:02x} 0x{payload:0{payload_len*2}x}")
			elif opcode == 1:
				bank_nr = payload
			elif opcode == 2:
				if crc.value != 0:
					raise MalformedBitstreamError(f"Wrong CRC is {crc.value:04x}")
			elif opcode == 5:
				try:
					self._freq_range = FreqRange(payload)
				except ValueError as ve:
					raise MalformedBitstreamError(f"Unknown value for frequency range {payload}") from ve
			elif opcode == 6:
				bank_width = payload + 1
			elif opcode == 7:
				bank_height = payload
			elif opcode == 8:
				bank_offset = payload
			elif opcode == 9:
				self._nosleep = (payload & NOSLEEP_MASK) != 0
				self._warmboot = (payload & WARMBOOT_MASK) != 0
			else:
				# opcode 4 (set boot address) not supported
				raise MalformedBitstreamError(f"Unknown opcode {opcode:1x}")
		
		self._read_cram_banks(cram)
		self._read_bram_banks(bram)
	
	def _get_cram_banks(self) -> Banks:
		cram = self._all_blank_cram_banks()
		self._write_cram_banks(cram)
		
		return cram
	
	def _get_bram_banks(self) -> Banks:
		bram = self._all_blank_bram_banks()
		self._write_bram_banks(bram)
		
		return bram
	
	def get_bitstream(self) -> bytes:
		with BytesIO() as bin_file:
			self.write_bin(bin_file)
			bitstream = bin_file.getvalue()
		
		return bitstream
	
	def write_bin(self, bin_file: BinaryIO):
		cram = self._get_cram_banks()
		bram = self._get_bram_banks()
		
		bin_out = BinOut(bin_file)
		
		# comment
		bin_out.write_comment(self._comment)
		
		# preamble
		bin_out.write_preamble()
		
		# frequency range
		bin_out.write_freq_range(self._freq_range)
		
		# CRC reset
		bin_out.crc_reset()
		
		# warmboot & nosleep
		bin_out.write_warmboot(self._warmboot, self._nosleep)
		
		# bank width
		bin_out.set_bank_width(self._spec.cram_width)
		# bank height
		bin_out.set_bank_height(self._spec.cram_height)
		# bank offset
		bin_out.set_bank_offset(0)
		
		# write CRAM
		for bank_number in range(len(cram)):
			bin_out.set_bank_number(bank_number)
			bin_out.write_cram(cram)
		
		# write BRAM
		chunk_size = 128
		bin_out.set_bank_width(self._spec.bram_width)
		bin_out.set_bank_height(chunk_size)
		for bank_number in range(len(bram)):
			bin_out.set_bank_number(bank_number)
			for bank_offset in range(0, self._spec.bram_height, chunk_size):
				bin_out.set_bank_offset(bank_offset)
				bin_out.write_bram(bram)
		
		# CRC check
		bin_out.crc_check()
		
		# wakeup
		bin_out.wakeup()
		
		# padding
		bin_out.write_bytes(b"\x00")
	
	def _read_cram_banks(self, cram: Banks) -> None:
		self._access_cram_banks(cram, True)
	
	def _write_cram_banks(self, cram: Banks) -> None:
		self._access_cram_banks(cram, False)
	
	def _access_cram_banks(self, cram: Banks, read: bool) -> None:
		for bank_nr, cram_bank in enumerate(cram):
			top = bank_nr%2 == 1
			right = bank_nr >= 2
			
			if top:
				y_range = list(reversed(range((self._spec.max_y+1)//2, self._spec.max_y)))
				io_y = self._spec.max_y
			else:
				y_range = list(range(1, (self._spec.max_y+1)//2))
				io_y = 0
			
			if right:
				x_range = list(reversed(range((self._spec.max_x+1)//2, self._spec.max_x+1)))
			else:
				x_range = list(range((self._spec.max_x+1)//2))
			
			# IO in x direction
			x_off = self._spec.tile_type_width[self._tile_types[TilePosition(x_range[0], y_range[0])]]
			io_width = self._spec.tile_type_width[TileType.IO]
			for tile_x in x_range[1:]:
				# width is defined by the other tile i the row, not the IO tile
				row_width = self._spec.tile_type_width[self._tile_types[TilePosition(tile_x, y_range[0])]]
				
				tile_data = self._tiles[TilePosition(tile_x, io_y)]
				
				cram_indices = [23, 25, 26, 27, 16, 17, 18, 19, 20, 14, 32, 33, 34, 35, 36, 37, 4, 5]
				if right:
					cram_indices = [row_width-1-i for i in cram_indices]
				
				for group, cram_y in enumerate([15, 14, 12, 13, 11, 10, 8, 9, 7, 6, 4, 5, 3, 2, 0, 1]):
					if read:
						tile_data[group, 0:io_width] = [cram_bank[cram_y, x_off+i] for i in cram_indices]
					else:
						for index, cram_x in enumerate(cram_indices):
							cram_bank[cram_y, x_off+cram_x] = tile_data[group, index]
				
				x_off += row_width
			
			y_off = self._spec.tile_height
			for tile_y in y_range:
				x_off = 0
				for tile_x in x_range:
					tile_pos = TilePosition(tile_x, tile_y)
					tile_data = self._tiles[tile_pos]
					tile_type = self._tile_types[tile_pos]
					tile_width = self._spec.tile_type_width[tile_type]
					
					cram_x_slice = slice(x_off, x_off+tile_width)
					if right or tile_type == TileType.IO:
						cram_x_slice = self.reverse_slice(cram_x_slice)
					index_slice = slice(0, tile_width)
					
					cram_y_slice = slice(y_off, y_off+self._spec.tile_height)
					if top:
						cram_y_slice = self.reverse_slice(cram_y_slice)
					
					if read:
						tile_data[:self._spec.tile_height, index_slice] = cram_bank[cram_y_slice, cram_x_slice]
					else:
						cram_bank[cram_y_slice, cram_x_slice] = tile_data[:self._spec.tile_height, index_slice]
					
					x_off += tile_width
				y_off += self._spec.tile_height
		
		# extra bits
		if read:
			self._extra_bits = []
			for extra in self._spec.extra_bits:
				if cram[extra.bank, extra.y, extra.x]:
					self._extra_bits.append(extra)
		else:
			for extra in self._extra_bits:
				cram[extra.bank, extra.y, extra.x] = True
	
	def _read_bram_banks(self, bram: Banks) -> None:
		self._access_bram_banks(bram, True)
	
	def _write_bram_banks(self, bram: Banks) -> None:
		self._access_bram_banks(bram, False)
	
	def _access_bram_banks(self, bram: Banks, read: bool) -> None:
		for bank_nr, bram_bank in enumerate(bram):
			top = bank_nr%2 == 1
			tile_x = self._spec.bram_cols[bank_nr//2]
			for block_nr in range(self._spec.bram_width//16):
				tile_y = block_nr*2 + 1
				if top:
					# in fact it should be (max_y-1)//2 but as max_y is always odd it yields the same result
					tile_y += self._spec.max_y//2
				bram_data = self._bram[TilePosition(tile_x, tile_y)]
				
				row_slice = slice((block_nr+1)*16-1, block_nr*16-1 if block_nr else None, -1)
				
				if read:
					bram_data[:, :] = np.reshape(bram_bank[:, row_slice], (16, 256))
				else:
					bram_bank[:, row_slice] = np.reshape(bram_data, (256, 16))
	
	@staticmethod
	def reverse_slice(org_slice: slice) -> slice:
		# only tested for |step| == 1
		step = -(org_slice.step or 1)
		if step < 0:
			# org step was positive
			
			if org_slice.stop == 0:
				# special case, always returns empty list
				return slice(org_slice.start, -1, step)
			
			if org_slice.start in (None, 0):
				stop = None
			else:
				stop = org_slice.start - 1
			
			if org_slice.stop is None:
				start = None
			else:
				start = org_slice.stop - 1
		else:
			# org step was negative
			
			if org_slice.stop == -1:
				# special case, always returns empty list
				return slice(org_slice.start, 0, step)
			
			if org_slice.start in (None, -1):
				stop = None
			else:
				stop = org_slice.start + 1
			
			if org_slice.stop is None:
				start = None
			else:
				start = org_slice.stop + 1
		
		return slice(start, stop, step)
	
	@classmethod
	def expect_bytes(cls, bin_file: BinaryIO, exp: bytes, crc: CRC, msg: str="Expected {exp} but got {val}") -> None:
		val = cls.get_bytes_crc(bin_file, len(exp), crc)
		
		if exp != val:
			raise MalformedBitstreamError(msg.format(exp=exp, val=val))
	
	@classmethod
	def get_bytes_crc(cls, bin_file: BinaryIO, size: int, crc: CRC) -> bytes:
		"""Get a specific number of bytes and update a CRC"""
		res = cls.get_bytes(bin_file, size)
		crc.update(res)
		return res
	
	@staticmethod
	def get_bytes(bin_file: BinaryIO, size: int) -> bytes:
		res = bin_file.read(size)
		
		if len(res) < size:
			raise EOFError()
		
		return res
	
	@staticmethod
	def get_line(file_obj) -> str:
		line = file_obj.readline()
		
		# empty string means EOF, '\n' means empty line
		if line == "":
			raise EOFError()
		
		return line
	
	@classmethod
	def create_blank(cls, asc_name: str="8k") -> "Configuration":
		spec = SPECS_BY_ASC[asc_name]
		config = cls(spec)
		
		return config
	
	@classmethod
	def create_from_asc(cls, asc_filename: str) -> "Configuration":
		with open(asc_filename, "r") as asc_file:
			asc_name = cls.device_from_asc(asc_file)
			config = cls.create_blank(asc_name)
			
			# reset for parsing
			asc_file.seek(0)
			
			config.read_asc(asc_file)
			return config
	
	@staticmethod
	def device_from_asc(asc_file: TextIO) -> str:
		for line in asc_file:
			line = line.strip()
			if line.startswith(".device"):
				parts = line.split()
				return parts[1]
		
		raise ValueError("asc file without device entry")
