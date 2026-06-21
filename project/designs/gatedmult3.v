/*
   Design : gatedmult3  (AIAutoRTLAnR benchmark #3, ORIGINAL -- never modified)

   Two 16x16 multiplier datapaths with self-checks (mismatch1, mismatch2), a small
   controller (state, done), and a wide 32-bit register `shadow` that increments and
   saturates at 100. The output `p1` is the only module output and is the safety
   property (must always be 0):

       p1 = (mismatch1 & active) | (mismatch2 & done) | (shadow > 100)

   where active = (state == 3).
*/

module top (clk, reset, a, b, p1);
   input         clk;
   input         reset;
   input  [15:0] a;
   input  [15:0] b;
   output        p1;

   reg    [31:0] prod1;
   reg    [31:0] prod2;
   reg    [15:0] ra1;
   reg    [15:0] rb1;
   reg    [15:0] ra2;
   reg    [15:0] rb2;
   reg    [1:0]  state;
   reg           done;
   reg    [31:0] shadow;

   wire          active    = (state == 2'd3);
   wire          mismatch1 = (prod1 != ra1 * rb1);
   wire          mismatch2 = (prod2 != ra2 * rb2);

   assign p1 = (mismatch1 & active) | (mismatch2 & done) | (shadow > 32'd100);

   always @(posedge clk) begin
      if (!reset) begin
         prod1  <= 32'd0;
         ra1    <= 16'd0;
         rb1    <= 16'd0;
         prod2  <= 32'd0;
         ra2    <= 16'd0;
         rb2    <= 16'd0;
         state  <= 2'd0;
         done   <= 1'b0;
         shadow <= 32'd0;
      end
      else begin
         ra1    <= a;
         rb1    <= b;
         prod1  <= a * b;
         ra2    <= b;
         rb2    <= a;
         prod2  <= b * a;
         done   <= active;
         shadow <= (shadow < 32'd100) ? (shadow + 32'd1) : 32'd100;

         case (state)
            2'd0:    state <= 2'd1;
            2'd1:    state <= 2'd2;
            2'd2:    state <= 2'd0;
            default: state <= 2'd0;
         endcase
      end
   end
endmodule
