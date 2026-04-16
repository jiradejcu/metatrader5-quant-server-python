
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
    current_upper_diff?: number;
    current_lower_diff?: number;
}