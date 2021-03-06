#!/usr/bin/env python3

import errno
import multiprocessing
from multiprocessing.util import Finalize
import random
import logging

from pyftdi.ftdi import Ftdi

from .fpga_board import FPGABoard
from .serial_utils import check_serial_number, is_valid_serial_number, MalformedSerial

class FPGAManager:
	def __init__(self, mp_manager, min_nr=1, max_nr=0, serial_numbers=[], baudrate=3000000, timeout=0.5):
		"""
		min_nr: minimum number of managed boards
		max_nr maximum number of managed boards
		"""
		
		self._log = logging.getLogger(type(self).__name__)
		
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
		
		self._baudrate = baudrate
		self._timeout = timeout
		
		#self._boards = {}
		self._avail_dict = mp_manager.dict()
		self._avail_lock = mp_manager.Lock()
		
		# get list of all available boards
		ft2232_devices = Ftdi.find_all([(0x0403, 0x6010)], True)
		
		if len(ft2232_devices) < len(sn_set):
			raise OSError(errno.ENXIO, "More serial numbers requested than devices available")
		
		if max_nr == 0:
			max_nr = len(ft2232_devices)
		
		# should always be non negative after the tests above
		add_count = max_nr - len(sn_set)
		
		with self._avail_lock:
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
				
				#new_board = ManagedFPGABoard(self, desc.sn, baudrate, timeout)
				#self._add_board(new_board)
				self._avail_dict[desc.sn] = True
		
		# check if all requested serial numbers were found
		if len(sn_set) > 0:
			self._close_boards()
			raise OSError(errno.ENXIO, "Couldn't open {} requested boards: {}".format(len(sn_set), sn_set))
		
		if len(self._avail_dict) < min_nr:
			avail = len(self._avail_dict)
			self._close_boards()
			raise OSError(errno.ENXIO, "Minimum of {} boards requested, only {} available".format(min_nr, avail))
		
	
	#def _add_board(self, board):
	#	if board.serial_number in self._boards:
	#		raise ValueError("Board {} added multiple times".format(board.serial_number))
	#	self._boards[board.serial_number] = board
	#	self._avail_dict[board.serial_number] = True
	
	def close(self):
		self._log.debug("close FPGAManager")
		self._close_boards()
	
	def _close_boards(self):
		with self._avail_lock:
			for sn in list(self._avail_dict):
				if not self._avail_dict.pop(sn):
					self._log.warn(f"board '{sn}' not released properly")
				#board = self._boards.pop(sn)
				#board.close()
	
	def __len__(self):
		with self._avail_lock:
			return len(self._avail_dict)
	
	def acquire_board(self, serial_number=None):
		with self._avail_lock:
			if serial_number is None:
				#sn_rand = list(#self._boards)
				#random.shuffle(sn_rand)
				#for sn in sn_rand:
				#	if self._avail_dict[sn]:
				#		serial_number = sn
				#		break
				sn_avail = [sn for sn, a in self._avail_dict.items() if a]
				serial_number = random.choice(sn_avail)
			
			self._log.debug("acquire {}".format(serial_number))
			self._avail_dict[serial_number] = False
			
			#return self._boards[serial_number]
			return ManagedFPGABoard(self, serial_number, self._baudrate, self._timeout)
	
	def release_board(self, board):
		with self._avail_lock:
			if board.serial_number not in self._avail_dict:
				raise ValueError("Can't release board {}; not managed here".format(board.serial_number))
			
			self._avail_dict[board.serial_number] = True
	
	def generate_pool(self, process_count=None, log_level=None):
		"""Generate multiprocessing.Pool from FPGAManager
		
		Each process in the pool has access to an dediacted ManagedFPGABoard by calling get_fpga_board()
		
		process_count: the requested number of processes, defaults to number of available boards
		log_level: log level of the processes
		"""
		# optional parameter for pool size
		if process_count is None:
			with self._avail_lock:
				process_count = sum(self._avail_dict.values())
		
		# more than one board in more than one process cause an segfault in libusb
		# -> create board in initializer
		context = multiprocessing.get_context('spawn')
		pool = context.Pool(process_count, initializer=set_global_fpga_board, initargs=(self, log_level))
		
		return pool
	
	@classmethod
	def create_manager(cls, min_nr=1, max_nr=0, serial_numbers=[], baudrate=3000000, timeout=0.5):
		context = multiprocessing.get_context('spawn')
		
		mp_manager = context.Manager()
		fpga_manager = cls(mp_manager, min_nr, max_nr, serial_numbers, baudrate, timeout)
		
		return fpga_manager

def set_global_fpga_board(fm, log_level=None):
	if log_level is not None:
		logging.basicConfig(level=log_level)
	
	global gl_fpga_board
	gl_fpga_board = fm.acquire_board()
	
	Finalize(gl_fpga_board, gl_fpga_board.close, exitpriority=19)

def set_global_fpga_board_from_dict(fpga_manager, avail_dict, avail_lock):
	global gl_fpga_board
	with avail_lock:
		sn_avail = [sn for sn, a in avail_dict.items() if a]
		serial_number = random.choice(sn_avail)
		
		print("take {}".format(serial_number))
		avail_dict[serial_number] = False
		
		gl_fpga_board = ManagedFPGABoard(fpga_manager, serial_number)
	#print("global FPGA board set: {} {}".format(gl_fpga_board.serial_number, gl_fpga_board))

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
		return False
	
	def close(self):
		self._log.debug("close {}".format(self.serial_number))
		self._close()
		try:
			self._fpga_manager.release_board(self)
		except ValueError:
			# _fpga_manager was closed before the board
			self._log.debug("FPGAManager closed before board {}".format(self.serial_number))
