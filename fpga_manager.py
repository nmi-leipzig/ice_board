#!/usr/bin/env python3

import errno
import multiprocessing
import random

from pyftdi.ftdi import Ftdi

from fpga_board import FPGABoard
from serial_utils import check_serial_number, is_valid_serial_number, MalformedSerial

class FPGAManager:
	def __init__(self, min_nr=1, max_nr=0, serial_numbers=[], baudrate=3000000, timeout=0.5):
		"""
		min_nr: minimum number of managed boards
		max_nr maximum number of managed boards
		"""
		
		# vaidate input
		if min_nr < 1:
			raise ValueError("Minimum has to be at least 1, {} too low".format(min_nr))
		
		if max_nr > 0 and min_nr > max_nr:
			raise ValueError("Minimum {} greater than maximum {}".format(min_nr, max_nr))
		
		if max_nr > 0 and len(serial_numbers) > max_nr:
			raise ValueError("Requested {} serial numbers, but limited number of managed boards to {}".format(len(serial_numbers), max_nr))
		
		for sn in serial_numbers:
			try:
				check_serial_number(sn)
			except MalformedSerial as ms:
				raise ValueError from ms
		
		sn_set = set(serial_numbers)
		if len(sn_set) != len(serial_numbers):
			raise ValueError("Some serial number requested multiple times")
		
		self._boards = {}
		self._available = set()
		self._manager = multiprocessing.Manager()
		self._avail_dict = self._manager.dict()
		self._acquire_lock = self._manager.Lock()
		
		# get list of all available boards
		ft2232_devices = Ftdi.find_all([(0x0403, 0x6010)], True)
		
		if len(ft2232_devices) < len(sn_set):
			raise OSError(errno.ENXIO, "More serial numbers requested than devices available")
		
		if max_nr == 0:
			max_nr = len(ft2232_devices)
		
		# should always be non negative after the tests above
		add_count = max_nr - len(sn_set)
		
		for desc, i_count in ft2232_devices:
			if not is_valid_serial_number(desc.sn) or i_count != 2:
				continue
			try:
				# open the boards with requested serial numbers
				sn_set.remove(desc.sn)
			except KeyError:
				# open additional boards
				if add_count == 0:
					if len(sn_set) == 0:
						break
					else:
						continue
				add_count -= 1
			
			new_board = ManagedFPGABoard(self, desc.sn, baudrate, timeout)
			self._add_board(new_board)
		
		# check if all requested serial numbers were found
		if len(sn_set) > 0:
			self._close_boards()
			raise OSError(errno.ENXIO, "Couldn't open {} requested boards: {}".format(len(sn_set), sn_set))
		
		if len(self._boards) < min_nr:
			self._close_boards()
		
		print(self._available)
		print(self._boards)
	
	def _add_board(self, board):
		if board.serial_number in self._boards:
			raise ValueError("Board {} added multiple times".format(board.serial_number))
		self._boards[board.serial_number] = board
		self._available.add(board.serial_number)
		self._avail_dict[board.serial_number] = True
	
	def close(self):
		self._close_boards()
	
	def _close_boards(self):
		for sn in list(self._boards):
			self._available.discard(sn)
			self._avail_dict.pop(sn)
			board = self._boards.pop(sn)
			board.close()
	
	def __len__(self):
		return len(self._boards)
	
	def acquire_board(self, serial_number=None):
		with self._acquire_lock:
			if serial_number is None:
				sn_rand = list(self._boards)
				random.shuffle(sn_rand)
				for sn in sn_rand:
					if self._avail_dict[sn]:
						serial_number = sn
						break
			
			self._available.remove(serial_number)
			print("acquire {}".format(serial_number))
			self._avail_dict[serial_number] = False
			
			return self._boards[serial_number]
	
	def release_board(self, board):
		if board.serial_number not in self._boards:
			raise ValueError("Can't release board {}; not managed here".format(board.serial_number))
		
		self._available.add(board.serial_number)
		self._avail_dict[board.serial_number] = True
	
	def generate_pool(self, process_count=None):
		# optional parameter for pool size
		if process_count is None:
			process_count = len(self._available)
		
		# more than one board in more than one process cause an segfault in libusb
		pool = multiprocessing.Pool(process_count, initializer=set_global_fpga_board, initargs=(self,))
		
		return pool

def set_global_fpga_board(fm):
	global gl_fpga_board
	gl_fpga_board = fm.acquire_board()
	print("global FPGA board set: {} {}".format(gl_fpga_board.serial_number, gl_fpga_board))

def print_fpga_manager():
	print(hex(id(gl_fpga_manager)), end=" ")

def get_fpga_board():
	return gl_fpga_board

class ManagedFPGABoard(FPGABoard):
	"""FPGABoard that is managed by an external instance.
	
	managed means created and closed
	"""
	def __init__(self, fpga_manager, serial_number, baudrate=3000000, timeout=0.5):
		super().__init__(serial_number, baudrate, timeout)
		self._fpga_manager = fpga_manager
	
	def __exit__(self, exc_type, exc_value, traceback):
		# leave connections open even if context is left
		#self._fpga_manager.release_board(self)
		pass
	
	def close(self):
		self._close()
