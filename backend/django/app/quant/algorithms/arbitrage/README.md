1. position sync => monitor position websocket connection health
2. calculate diff function to signal Binance order
	1) diff >= 0.3%: open Binance limit order (fix size = target - current position size) @ best bid/ask
	2) 0.3% >= diff >= 0.2%: cancel and open Binance limit order @ best bid/ask
	3) diff < 0.2%: cancel Binance limit order @ best bid/ask => close partial position
		e.g.
			3.1 Oz. => close 0.1 Oz.
			3.7 Oz. => open market 0.3 Oz.

	4) diff < -0.1%: cancel and open Binance limit order @ best ask/bid

	variable
		1. trigger open % = 0.3%
		2. trigger cancel % = 0.2%
		3. trigger TP % = -0.1%
3. visualize price diff, funding rate on admin page
4. set trigger open and trigger TP in admin page