#!/usr/bin/env python3

from array import array
import timeit

class Configuration:
	"""represents the configuration of a FPGA"""
	
	def __init__(self):
		#self._chip = "8k"
		pass
		#TODO: decide list of bool, bytearray or array('B')
		# most frequent operations: set, read, to string

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
	
