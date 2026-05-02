
export interface IPairDetails {
    pairStatus?: string;
    entryAction?: string;
    entrySize?: number;
    entrySymbol?: string;
    time_update_entry?: string;
    hedgeAction?: string;
    hedgeSize?: number;
    hedgeSymbol?: string;
    time_update_hedge?: string;
    entryPrice?: number;
    hedgePrice?: number;
    unrealizedTotal?: number;
    ask_diff?: number;
    bid_diff?: number;
}