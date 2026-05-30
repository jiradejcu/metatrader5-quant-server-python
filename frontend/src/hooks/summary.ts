/* eslint-disable @typescript-eslint/no-explicit-any */
import { useQuery } from '@tanstack/react-query';

interface IArbitrageSummary {
  pausePositionSync?: string;
  spread?: number;
  pairStatus?: string;
  primaryAction?: string;
  primaryMarkPrice?: number;
  hedgeMarkPrice?: number;
  primaryPrice?: number;
  hedgePrice?: number;
  primarySize?: number;
  hedgeSize?: number;
  hedgeAction?: string;
  unrealizedTotal?: number;
  time_update_hedge?: string;
  time_update_primary?: string;
  netExpose?: number;
  netExposeAction?: string;
  primarySymbol?: string;
  hedgeSymbol?: string;
  price_diff_percent?: number;
  gridBotStatus?: string;
  ask_diff?: number;
  bid_diff?: number;
}

export const useGetSummaryStreamData = (url: string) => {
  const { data: arbitrageSummary, isLoading } = useQuery({
    queryKey: ['arbitrage', 'summary', url],
    enabled: false,
    staleTime: Infinity, // Keep the data fresh as it comes from the stream
  });

  // Destructuring and set dafault values
    const {
        pausePositionSync = 'Active',
        gridBotStatus = 'Inactive',
        spread = 0,
        pairStatus = 'Idle',
        primaryAction = 'N/A',
        primaryMarkPrice = 0,
        hedgeMarkPrice = 0,
        primaryPrice = 0,
        hedgePrice = 0,
        primarySize = 0,
        hedgeSize = 0,
        hedgeAction = 'N/A',
        unrealizedTotal = 0,
        time_update_hedge = '-',
        time_update_primary = '-',
        netExpose = 0,
        netExposeAction = 'Safe',
        primarySymbol = 'default',
        hedgeSymbol = 'default',
        price_diff_percent = 0.0,
        ask_diff = undefined,
        bid_diff = undefined,
    } = (arbitrageSummary || {}) as IArbitrageSummary;

    return {
        isLoading,
        pausePositionSync,
        gridBotStatus,
        spread,
        pairStatus,
        primaryAction,
        primaryMarkPrice,
        hedgeMarkPrice,
        primaryPrice,
        hedgePrice,
        primarySize,
        hedgeSize,
        hedgeAction,
        unrealizedTotal,
        time_update_hedge,
        time_update_primary,
        netExpose,
        netExposeAction,
        primarySymbol,
        hedgeSymbol,
        price_diff_percent,
        ask_diff,
        bid_diff
     }
}
