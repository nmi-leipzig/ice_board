module echo_fpga_top
#(
	parameter CLK_PER_BIT = 4
)
(
	input clk,
	input rx,
	output tx,
	output reg [7:0] led
);
	assign tx = rx;
	
	generate
	genvar gi;
	for(gi=0; gi<7; gi=gi+1)
	begin
		always @(posedge clk)
			led[gi] <= led[gi+1];
	end
	endgenerate
	
	always @(posedge clk)
		led[7] <= rx;
	
endmodule
