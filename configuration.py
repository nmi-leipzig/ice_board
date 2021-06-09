#!/usr/bin/env python3

import binascii
import os
from array import array
import timeit
import enum
from typing import BinaryIO, Iterable, List, NamedTuple, TextIO, Tuple

from .device_data import SPECS_BY_ASC, TileType, BRAMMode, DeviceSpec, TilePosition, Bit

class ExtraBit(NamedTuple):
	bank: int
	x: int
	y: int

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
		self._warmboot = True
		self._nosleep = False
		self._extra_bits = []
		
		for pos, ttype in self._spec.get_tile_types():
			width = self._spec.tile_type_width[ttype]
			height = self._spec.tile_height
			data = tuple([False]*width for _ in range(height))
			self._tiles[pos] = data
			self._tiles_by_type.setdefault(ttype, []).append(pos)
			self._tile_types[pos] = ttype
			
			if ttype == TileType.RAM_B:
				self._bram[pos] = tuple([False]*256 for _ in range(16))
		
	
	def get_bit(self, x: int, y: int, group: int, index: int) -> bool:
		return self._tiles[(x, y)][group][index]
	
	def get_bits(self, tile: TilePosition, bits: Iterable[Bit]) -> Tuple[bool, ...]:
		tile_data = self._tiles[tile]
		values = [tile_data[b.group][b.index] for b in bits]
		
		return tuple(values)
	
	def set_bit(self, x: int, y: int, group: int, index: int, value: bool) -> None:
		self._tiles[(x, y)][group][index] = value
	
	def set_bits(self, tile: TilePosition, bits: Iterable[Bit], values: Iterable[bool]) -> None:
		tile_data = self._tiles[tile]
		for i, b in enumerate(bits):
			tile_data[b.group][b.index] = values[i]
	
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
	def get_from_bram_data(cls, bram_data: Iterable[Iterable[bool]], address: int, mode: BRAMMode=BRAMMode.BRAM_512x8) -> int:
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
	def set_in_bram_data(cls, bram_data: Iterable[Iterable[bool]], address: int, value: int, mode: BRAMMode=BRAMMode.BRAM_512x8) -> None:
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
	
	def read_opcodes(self, bin_file: BinaryIO) -> List[Tuple[int, int, int]]:
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
		
		self.comment = b"".join(com_list).decode("utf-8")
		
		# as Lattice' own tools create faulty comments just search for preamble instead of expecting it
		last_four = [None]*4
		while last_four != [b"\x7e", b"\xaa", b"\x99", b"\x7e"]:
			last_four = last_four[1:]
			last_four.append(self.get_bytes_crc(bin_file, 1, crc))
		
		print(f"found preamble at {bin_file.tell()-4}")
		
		block_nr = None
		block_width = None
		block_height = None
		block_offset = None
		
		res = []
		def get_data_len():
			try:
				return block_width*block_height//8
			except TypeError as te:
				raise MalformedBitstreamError("Block height and width have to be set before writig data") from te
		
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
			
			print(f"found command at {file_offset}: 0x{command:02x} 0x{payload:0{payload_len*2}x}")
			res.append((file_offset, command, payload))
			
			if opcode == 0:
				if payload == 1:
					data_len = get_data_len()
					data = self.get_bytes_crc(bin_file, data_len, crc)
					self.expect_bytes(bin_file, b"\x00\x00", crc, "Expected 0x{exp:04x} after CRAM data, got 0x{val:04x}")
					print(f"\tCRAM data {data_len} bytes")
				elif payload == 3:
					data_len = get_data_len()
					data = self.get_bytes_crc(bin_file, data_len, crc)
					self.expect_bytes(bin_file, b"\x00\x00", crc, "Expected 0x{exp:04x} after BRAM data, got 0x{val:04x}")
					print(f"\tBRAM data {data_len} bytes")
				elif payload == 5:
					crc.reset()
				elif payload == 6:
					# wakeup -> ignore everything after that
					break
				else:
					raise MalformedBitstreamError(f"Unsupported Command: 0x{command:02x} 0x{payload:0{payload_len*2}x}")
			elif opcode == 1:
				block_nr = payload
			elif opcode == 2:
				if crc.value != 0:
					raise MalformedBitstreamError(f"Wrong CRC is {crc.value:04x}")
			#elif opcode == 5:
			#	
			elif opcode == 6:
				block_width = payload + 1
			elif opcode == 7:
				block_height = payload
			elif opcode == 8:
				block_offset = payload
			#elif opcode == 9:
			#	
			# opcode 4 (set boot address) not supported
		
		return res
	
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
