#!/usr/bin/env python3

import re
import subprocess
from itertools import product
import time
import logging
import argparse

ALLOWED_DIGITS = "0123456789ABCDEFGHIJKLMNOPQRSTU"

KNOWN_GROUPS = {
	"E": "Leipzig",
	"U": "Lübeck",
	"P": "privat",
}

KNOWN_BOARDS = {
	"8": "Lattice iCE40HX8K-B-EVN"
}

class MalformedSerial(Exception):
	pass

def serial_number_checksum(serial_number):
	# compute checksum
	weights = (13, 11, 1, 7, 5, 3)
	mod_sum = 0
	for i in range(6):
		mod_sum += weights[i] * int(serial_number[i], 31)
	
	return mod_sum % 31

def check_serial_number(serial_number):
	if len(serial_number) != 6:
		raise MalformedSerial("Serial number should contain exactly 6 digits, but contains {}".format(len(serial_number)))
	for digit in serial_number:
		try:
			check_digit(digit)
		except ValueError as ve:
			raise MalformedSerial() from ve
	
	checksum = serial_number_checksum(serial_number)
	if checksum != 0:
		raise MalformedSerial("Invalid check digit in serial number, remainder is {}".format(checksum % 31))

def get_serial_number(usb_serial_device):
	udevadm_out = subprocess.check_output(["udevadm", "info", "-q", "property", "{}".format(usb_serial_device)], universal_newlines=True)
	res = re.search(r'ID_SERIAL_SHORT=(?P<serial>.*)', udevadm_out)
	if res is None:
		raise Exception("No serial found for {}".format(usb_serial_device))
	return res.group("serial")

def decode_serial_number(serial_number):
	str_list = [serial_number, ":\n"]
	
	group = serial_number[0]
	try:
		dec_group = KNOWN_GROUPS[group]
	except KeyError:
		dec_group = "unknown group"
	str_list.append("Group: {} -> {}\n".format(group, dec_group))
	
	board_type = serial_number[1]
	try:
		dec_board = KNOWN_BOARDS[board_type]
	except KeyError:
		dec_board = "unknown board"
	str_list.append("Board: {} -> {}\n".format(board_type, dec_board))
	
	checksum = serial_number[2]
	dec_checksum = int(checksum, 31)
	str_list.append("Checksum: {} -> {}\n".format(checksum, dec_checksum))
	
	seq = serial_number[3:]
	dec_seq = int(seq, 31)
	str_list.append("Sequential number: {} -> {}\n".format(seq, dec_seq))
	
	return "".join(str_list)

def check_digit(digit):
	if len(digit) != 1:
		raise ValueError("Not a single digit but {} digits".format(len(digit)))
	if digit not in ALLOWED_DIGITS:
		raise ValueError("Invalid digit '{}'".format(digit))

def create_serial_range(sequential_range, board_type="8", group="E"):
	serial_list = [create_serial_number(seq, board_type, group) for seq in sequential_range]
	
	return serial_list

def create_serial_number(sequential_number, board_type="8", group="E"):
	if sequential_number < 0:
		raise ValueError("sequential number has to be positive")
	upper_limit = pow(len(ALLOWED_DIGITS), 3)
	if sequential_number >= upper_limit:
		raise ValueError("sequential number has to be less than {}".format(upper_limit))
	
	check_digit(board_type)
	check_digit(group)
	
	digits = []
	for i in range(3):
		digits.append(ALLOWED_DIGITS[sequential_number%31])
		sequential_number //= 31
	digits.reverse()
	assert sequential_number == 0, "Sequential number was too large, despite previous checks"
	
	tmp_serial = "{}{}0{}".format(group, board_type, "".join(digits))
	checksum = serial_number_checksum(tmp_serial)
	serial = tmp_serial[:2] + ALLOWED_DIGITS[(31-checksum) % 31] + tmp_serial[3:]
	
	check_serial_number(serial)
	
	return serial

def check_allowed_digits(digit_string, base):
	if len(digit_string) != base:
		raise Exception("{} digits required, but {} found.".format(base, len(digit_string)))
	for i in range(base):
		if i != int(digit_string[i], base):
			raise Exception("{}. digit is {} which is not equal to {}".format(i, digit_string[i], i))

def test_single_errors(valid_serial):
	errors = 0
	for i in range(6):
		prefix = valid_serial[:i]
		suffix = valid_serial[i+1:]
		for s in ALLOWED_DIGITS:
			if s == valid_serial[i]:
				continue
			tmp_serial = prefix + s + suffix
			
			checksum = serial_number_checksum(tmp_serial)
			if checksum == 0:
				logging.error("Valid checksum for altered number {} (originally {})".format(tmp_serial, valid_serial))
				errors += 1
			
	return errors

def test_all_serials():
	errors = 0
	count = 0
	todo = pow(len(ALLOWED_DIGITS), 5)
	start_time = time.time()
	last_time = start_time
	# construct serial
	for d in product(ALLOWED_DIGITS, repeat=5):
		count += 1
		#create_serial_number()
		tmp_serial = "".join(d[:2]) + "0" + "".join(d[2:])
		checksum = serial_number_checksum(tmp_serial)
		current_serial = tmp_serial[:2] + ALLOWED_DIGITS[(31-checksum) % 31] +tmp_serial[3:]
		# test serial
		errors += test_single_errors(current_serial)
		
		if time.time() - last_time > 60:
			last_time = time.time()
			passed_time = last_time-start_time
			eta = int(passed_time/count*todo)
			logging.info("current {} , {} of {} after {} s, {} s remaining (from {})".format(current_serial, count, todo, int(passed_time), eta-int(passed_time), eta))
		
	
	return errors

def create_argument_parser():
	arg_parser = argparse.ArgumentParser()
	arg_parser.set_defaults(func=None)
	sub_parser = arg_parser.add_subparsers()
	
	arg_gen = sub_parser.add_parser("generate", aliases=["gen"])
	arg_gen.add_argument("-g", "--group", default="E", type=str, choices=ALLOWED_DIGITS, help="organizational group the device belongs to")
	arg_gen.add_argument("-b", "--board_type", default="8", type=str, choices=ALLOWED_DIGITS, help="type of the physical device")
	arg_gen.add_argument("-s", "--sequential", default=0, type=int, help="first sequential number")
	arg_gen.add_argument("-n", "--number", default=1, type=int, help="amount of serial numbers to be generated")
	arg_gen.set_defaults(func=generate)
	
	arg_check = sub_parser.add_parser("check_all")
	arg_check.set_defaults(func=check_all)
	
	arg_decode = sub_parser.add_parser("decode", aliases=["dec"])
	arg_decode.add_argument("-s", "--serial_number", default=None, type=str, required=True, help="serial number to be decoded")
	arg_decode.set_defaults(func=decode)
	
	return arg_parser

def generate(arguments):
	serial_list = create_serial_range(
		range(arguments.sequential, arguments.sequential+arguments.number),
		arguments.board_type,
		arguments.group
	)
	for serial_number in serial_list:
		print(serial_number)

def check_all(arguments):
	check_allowed_digits(ALLOWED_DIGITS, 31)
	errors = test_all_serials()
	print("{} errors found".format(errors))

def decode(arguments):
	description = decode_serial_number(arguments.serial_number)
	
	print(description)

if __name__ == "__main__":
	logging.basicConfig(level=logging.DEBUG)
	
	parser = create_argument_parser()
	arguments = parser.parse_args()
	
	if arguments.func is None:
		parser.print_help()
	else:
		arguments.func(arguments)
