from dataclasses import dataclass
from typing import NamedTuple, Tuple, Dict
import enum

TileType = enum.Enum("TileType", ["LOGIC", "IO", "RAM_T", "RAM_B"])
class BRAMMode(enum.Enum):
	BRAM_256x16 = 0
	BRAM_512x8 = 1
	BRAM_1024x4 = 2
	BRAM_2048x2 = 3

class TilePosition(NamedTuple):
	x: int
	y: int

class Bit(NamedTuple):
	group: int
	index: int

@dataclass(frozen=True)
class DeviceSpec:
	asc_name: str
	
	max_x: int
	max_y: int
	cram_width: int
	cram_height: int
	bram_width: int
	bram_height: int
	
	bram_cols: Tuple[int, ...]
	tile_type_width: Dict[TileType, int]
	
	
	tile_height: int = 16
	
	def get_tile_types(self):
		# IO
		for y in range(1, self.max_y):
			yield TilePosition(0, y), TileType.IO
			yield TilePosition(self.max_x, y), TileType.IO
		for x in range(1, self.max_x):
			yield TilePosition(x, 0), TileType.IO
			yield TilePosition(x, self.max_y), TileType.IO
		
		# RAM & LOGIC
		for x in range(1, self.max_x):
			for y in range(1, self.max_y):
				if x in self.bram_cols:
					if y%2 == 0:
						ttype = TileType.RAM_T
					else:
						ttype = TileType.RAM_B
				else:
					ttype = TileType.LOGIC
				yield TilePosition(x, y), ttype
	

SPECS = (
	DeviceSpec(
		"8k",
		33,
		33,
		872,
		272,
		128,
		256,
		(8, 25),
		{TileType.IO: 18, TileType.RAM_T: 42, TileType.RAM_B: 42, TileType.LOGIC: 54}
	),
)

SPECS_BY_ASC = {d.asc_name: d for d in SPECS}
