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
]
