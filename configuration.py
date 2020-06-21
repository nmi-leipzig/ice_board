#!/usr/bin/env python3

from array import array
import timeit

from device_data import SPECS_BY_ASC, TileType

class Configuration:
	"""represents the configuration of a FPGA"""
	
	def __init__(self, device_spec):
		self._spec = device_spec
		self.clear()
	
	def clear(self):
		self._bram = {}
		self._tiles = {}
		self._tiles_by_type = {}
		
		for pos, ttype in self._spec.get_tile_types():
			width = self._spec.tile_type_width[ttype]
			height = self._spec.tile_height
			data = tuple([False]*width for _ in range(height))
			self._tiles[pos] = data
			self._tiles_by_type.setdefault(ttype, []).append(pos)
			
			if ttype == TileType.RAM_B:
				self._bram[pos] = tuple([False]*256 for _ in range(16))
	
	@classmethod
	def create_blank(cls, asc_name="8k"):
		spec = SPECS_BY_ASC[asc_name]
		config = cls(spec)
		
		return config
	
	@classmethod
	def create_from_asc(cls, asc_filename):
		with open(asc_filename, "r") as asc_file:
			asc_name = cls.device_from_asc(asc_file)
			config = cls.create_blank(asc_name)
			
			# reset for parsing
			asc_file.seek(0)
			
			config.read_asc(asc_file)
			return config
	
	@staticmethod
	def device_from_asc(asc_file):
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
	
