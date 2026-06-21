/*
   Design : gatedmult  (AIAutoRTLAnR benchmark, ORIGINAL -- never modified)

   A 16x16 multiplier datapath with a self-check, plus a small controller.
   The product is registered (prod <= a*b) alongside the operands (ra, rb); the
   self-check `mismatch` compares the stored product against ra*rb. The output
   `p1` is the only module output and is the safety property (must always be 0).
*/

module top (clk, reset, a, b, p1);
   input         clk;
   input         reset;
   input  [15:0] a;
   input  [15:0] b;
   output        p1;

   reg    [31:0] prod;
   reg    [15:0] ra;
   reg    [15:0] rb;
   reg    [1:0]  state;

   wire          active   = (state == 2'd3);
   wire          mismatch = (prod != ra * rb);

   assign p1 = mismatch & active;

   always @(posedge clk) begin
      if (!reset) begin
         prod  <= 32'd0;
         ra    <= 16'd0;
         rb    <= 16'd0;
         state <= 2'd0;
      end
      else begin
         ra   <= a;
         rb   <= b;
         prod <= a * b;

         case (state)
            2'd0:    state <= 2'd1;
            2'd1:    state <= 2'd2;
            2'd2:    state <= 2'd0;
            default: state <= 2'd0;
         endcase
      end
   end
endmodule
