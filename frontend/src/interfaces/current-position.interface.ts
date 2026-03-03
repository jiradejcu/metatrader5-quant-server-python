
export interface IPairDetails {
    pairStatus?: string;
    binanceAction?: string;
    binanceSize?: number;
    binanceSymbol?: string;
    time_update_binance?: string;
    mt5Action?: string;
    mt5Size?: number;
    mt5Symbol?: string;
    time_update_mt5?: string;
    binanceEntry?: number;
    mt5Entry?: number;
    unrealizedBinance?: number;
    current_upper_diff?: number;
    current_lower_diff?: number;
}