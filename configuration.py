#!/usr/bin/env python3

from array import array
import timeit
import enum
from typing import NamedTuple, TextIO, Iterable

from device_data import SPECS_BY_ASC, TileType, DeviceSpec, TilePosition, Bit

class ExtraBit(NamedTuple):
	bank: int
	x: int
	y: int

TILE_TYPE_TO_ASC_ENTRY = {
	TileType.LOGIC: "logic_tile",
	TileType.IO: "io_tile",
	TileType.RAM_T: "ramt_tile",
	TileType.RAM_B: "ramb_tile",
}

ASC_ENTRY_TO_TILE_TYPE = {a:t for t, a in TILE_TYPE_TO_ASC_ENTRY.items()}

class Configuration:
	"""represents the configuration of a FPGA"""
	
	def __init__(self, device_spec: DeviceSpec):
		self._spec = device_spec
		self.clear()
	
	def clear(self):
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
		
	
	def get_bits(self, tile: TilePosition, bits: Iterable[Bit]):
		tile_data = self._tiles[tile]
		values = [tile_data[b.group][b.index] for b in bits]
		
		return tuple(values)
	
	def set_bits(self, tile: TilePosition, bits: Iterable[Bit], values: Iterable[bool]):
		tile_data = self._tiles[tile]
		for i, b in enumerate(bits):
			tile_data[b.group][b.index] = values[i]
	
	def read_asc(self, asc_file: TextIO):
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
	
	def write_asc(self, asc_file: TextIO):
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
				asc_file.write("".join(f"{b:b}" for b in row))
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
	
	@staticmethod
	def get_line(file_obj):
		line = file_obj.readline()
		
		# empty string means EOF, '\n' means empty line
		if line == "":
			raise EOFError()
		
		return line
	
	@classmethod
	def create_blank(cls, asc_name: str="8k"):
		spec = SPECS_BY_ASC[asc_name]
		config = cls(spec)
		
		return config
	
	@classmethod
	def create_from_asc(cls, asc_filename: str):
		with open(asc_filename, "r") as asc_file:
			asc_name = cls.device_from_asc(asc_file)
			config = cls.create_blank(asc_name)
			
			# reset for parsing
			asc_file.seek(0)
			
			config.read_asc(asc_file)
			return config
	
	@staticmethod
	def device_from_asc(asc_file: TextIO):
		for line in asc_file:
			line = line.strip()
			if line.startswith(".device"):
				parts = line.split()
				return parts[1]
		
		raise ValueError("asc file without device entry")

class BLConf:
	def __init__(self):
		self._data = [False] * 692
	
	def get(self, index):
		return self._data[index]
	
	def set(self, index, value):
		self._data[index] = value

class BAConf:
	def __init__(self):
		self._data = bytearray([0]*((692+7)//8))
	
	def get(self, index):
		return (self._data[index//8] >> index%8) & 1
	
	def set(self, index, value):
		if value == 0:
			self._data[index//8] |= (1 << index%8)
		else:
			self._data[index//8] &= (1 << index%8) & 0xff

class AConf:
	def __init__(self):
		self._data = array("B", [0]*((692+7)//8))
	
	def get(self, index):
		return (self._data[index//8] >> index%8) & 1
	
	def set(self, index, value):
		if value:
			self._data[index//8] |= (1 << index%8)
		else:
			self._data[index//8] &= (1 << index%8) & 0xff

if __name__ == "__main__":
	# list of bools is fastest
	for c in (BLConf, BAConf, AConf):
		print(c)
		d = c()
		for i in range(478, 486):
			print(f"access {i}")
			print(timeit.timeit(f"d.get({i})", globals=globals()))
		
		for v in (False, True):
			for i in range(478, 486):
				print(f"setting {i} to {v}")
				print(timeit.timeit(f"d.set({i}, {v})", globals=globals()))
	
