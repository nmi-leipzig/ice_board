#!/usr/bin/env python3

import os
import sys
from array import array
import json

sys.path.append(
	os.path.dirname(
		os.path.dirname(
			os.path.dirname(os.path.abspath(__file__))
		)
	)
)

from serial_writer import SerialWriter

def store_variant(eeprom, filename, variant):
	mainname, extension = os.path.splitext(filename)
	new_filename = "{}.{}{}".format(mainname, variant, extension)
	
	with open(new_filename, "wb") as out_file:
		out_file.write(eeprom)
	
	return new_filename

def load_eeprom(filename):
	with open(filename, "rb") as in_file:
		eeprom = array("B", in_file.read())
	
	return eeprom

def fix_checksum(eeprom):
	checksum = SerialWriter.eeprom_checksum(eeprom)
	
	eeprom[-2] = (checksum & 0xff)
	eeprom[-1] = (checksum >> 8)

def add_case(case_dict, eeprom, filename, variant, faulty):
	"""
	faulty = triple of boolean,
	True iff check_eeprom, check_eeprom_checksum respectively check_eeprom_strings throws an AssertionError
	"""
	case_name = store_variant(eeprom, filename, variant)
	assert case_name not in case_dict, "Two test cases named '{}'".format(case_name)
	
	case_dict[case_name] = faulty

if __name__ == "__main__":
	serial_filename = "eeprom_serial.bin"
	no_serial_filename = "eeprom_no_serial.bin"
	"""
	#manufaturerer, product and serial number
		#start before string area
		#end after string area
		#inconsistent length
		#wrong type
		#unexpected start point (gaps)
	"""
	
	case_dict = {
		serial_filename: (False, False, False),
		no_serial_filename: (False, False, False)
	}
	for filename in (serial_filename, no_serial_filename):
		original = load_eeprom(filename)
		
		# wrong EEPROM size
		eeprom = original[:-2]
		fix_checksum(eeprom)
		add_case(case_dict, eeprom, filename, "too_short", (True, False, False))
		
		eeprom = original[:]
		eeprom.extend((0x00, 0x00))
		fix_checksum(eeprom)
		add_case(case_dict, eeprom, filename, "too_long", (True, False, False))
		
		#wrong checksum high
		eeprom = original[:]
		eeprom[-2] += 1
		add_case(case_dict, eeprom, filename, "checksum_high", (True, True, False))
		
		#wrong checksum
		eeprom[-1] -= 1
		add_case(case_dict, eeprom, filename, "checksum", (True, True, False))
		
		#wrong checksum low
		eeprom[-2] = original[-2]
		add_case(case_dict, eeprom, filename, "checksum_low", (True, True, False))
		
		#checksum zero
		eeprom[-2] = 0x00
		eeprom[-1] = 0x00
		add_case(case_dict, eeprom, filename, "checksum_zero", (True, True, False))
		
		#checksum all 1
		eeprom[-2] = 0xff
		eeprom[-1] = 0xff
		add_case(case_dict, eeprom, filename, "checksum_one", (True, True, False))
	
	serial_eeprom = load_eeprom(serial_filename)
	no_serial_eeprom = load_eeprom(no_serial_filename)
	
	#serial_number flag not set but offset and/or length
	eeprom = no_serial_eeprom[:]
	eeprom[0x12] = serial_eeprom[0x12]
	eeprom[0x13] = serial_eeprom[0x13]
	fix_checksum(eeprom)
	add_case(case_dict, eeprom, no_serial_filename, "sn_flag", (True, False, True))
	
	# gap in front of serial number
	eeprom = serial_eeprom[:]
	offset = serial_eeprom[0x12]
	length = serial_eeprom[0x13]
	eeprom[offset] = 0x00
	eeprom[offset+1] = 0x00
	for addr in range(offset, offset+length+4):
		eeprom[addr+2] = serial_eeprom[addr]
	fix_checksum(eeprom)
	add_case(case_dict, eeprom, serial_filename, "sn_gap", (True, False, True))
	
	with open("faulty_eeprom.json", "w") as json_file:
		json.dump(case_dict, json_file, indent=1, sort_keys=True)
	
