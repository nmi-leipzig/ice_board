module sum_fpga_top
#(
	parameter INPUT_LENGTH = 20,
	parameter CLK_PER_BIT = 4
)
(
	input clk,
	input rx,
	output tx,
	output [7:0] led
);
	localparam COUNTER_WIDTH = $clog2(INPUT_LENGTH+1);
	
	localparam STATE_RESET = 3'b000;
	localparam STATE_WAIT_IN = 3'b001;
	localparam STATE_RECV_IN = 3'b011;
	localparam STATE_SEND_OUT = 3'b010;
	localparam STATE_WAIT_OUT = 3'b110;
	
	reg [2:0] state;
	reg [2:0] next_state;
	
	reg [COUNTER_WIDTH-1:0] counter;
	
	wire [7:0] data_in;
	wire rx_done;
	wire tx_done;
	reg tx_start;
	reg [7:0] sum;
	assign led = sum;
	
	uart_rx #(.CLK_PER_BIT(CLK_PER_BIT)) receiver(
		.clk(clk),
		.rx(rx),
		.data(data_in),
		.rx_done(rx_done)
	);
	
	uart_tx #(.CLK_PER_BIT(CLK_PER_BIT)) sender(
		.clk(clk),
		.data(sum),
		.tx_start(tx_start),
		.tx(tx),
		.tx_done(tx_done)
	);
	
	always @(posedge clk)
		state <= next_state;
	
	always @(*)
	begin
		next_state = state;
		case(state)
		STATE_RESET:
			next_state = STATE_WAIT_IN;
		STATE_WAIT_IN:
			if (rx_done)
				next_state = STATE_RECV_IN;
		STATE_RECV_IN:
			if (counter == INPUT_LENGTH)
				next_state = STATE_SEND_OUT;
			else
				next_state = STATE_WAIT_IN;
		STATE_SEND_OUT:
			next_state = STATE_WAIT_OUT;
		STATE_WAIT_OUT:
			if (tx_done)
				next_state = STATE_RESET;
		endcase
	end
	
	always @(posedge clk)
	begin
		case(next_state)
		STATE_RESET:
		begin
			sum <= 0;
			counter <= 0;
			tx_start <= 1'b0;
		end
		STATE_RECV_IN:
		begin
			counter <= counter + 1;
			if (data_in)
				sum <= sum + 1;
		end
		STATE_SEND_OUT:
			tx_start <= 1'b1;
		STATE_WAIT_OUT:
			tx_start <= 1'b0;
		endcase
	end
	
endmodule
