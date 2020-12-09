# ice_board

Python package to configure and communicate with development boards consisting of an ice40 FPGA and an FTDI USB UART IC.

The primary use case is as a submodule for other projects.

## Tests
As the project directory is the same as the package directory, it's necessary to set the top-level-directory
to the directory above the project directory.
Otherwise the relative imports will not work.

	python3 -m unittest discover -v -t ..
