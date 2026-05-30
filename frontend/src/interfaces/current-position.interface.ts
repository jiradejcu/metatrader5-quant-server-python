
export interface IPairDetails {
    pairStatus?: string;
    primaryAction?: string;
    primarySize?: number;
    primarySymbol?: string;
    time_update_primary?: string;
    hedgeAction?: string;
    hedgeSize?: number;
    hedgeSymbol?: string;
    time_update_hedge?: string;
    primaryPrice?: number;
    hedgePrice?: number;
    unrealizedTotal?: number;
    ask_diff?: number;
    bid_diff?: number;
}
