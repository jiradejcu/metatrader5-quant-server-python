PAIRS = [
    {
        'primary': {'exchange': 'binance', 'symbol': 'PAXGUSDT'},
        'hedge': {'exchange': 'mt5',     'symbol': 'XAUUSD'},
        'contract_size': 100,
        'minimum_trade_amount': 1,
},
    {
        'primary': {'exchange': 'binance', 'symbol': 'XAUUSDT'},
        'hedge': {'exchange': 'mt5',     'symbol': 'XAUUSD'},
        'contract_size': 100,
        'minimum_trade_amount': 1,
},
    {
        'primary': {'exchange': 'binance', 'symbol': 'XAGUSDT'},
        'hedge': {'exchange': 'mt5',     'symbol': 'XAGUSD'},
        'contract_size': 5000,
        'minimum_trade_amount': 50,
},
    {
        'primary': {'exchange': 'binance', 'symbol': 'XAUUSDT'},
        'hedge': {'exchange': 'mt5',     'symbol': 'XAUUSD+'},
        'contract_size': 100,
        'minimum_trade_amount': 1,
        'timezone_offset_hours': 3,
    },
    # Hyperliquid primary. Hyperliquid uses bare coin names (e.g. 'BTC') and its
    # signed size (szi) is already in coin units, so contract_size is 1. Adjust
    # the hedge symbol / contract_size to your actual instrument before trading.
    {
        'primary': {'exchange': 'hyperliquid', 'symbol': 'BTC'},
        'hedge': {'exchange': 'mt5',           'symbol': 'BTCUSD'},
        'contract_size': 1,
        'minimum_trade_amount': 1,
    },
]
