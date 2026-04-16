/* eslint-disable @typescript-eslint/no-explicit-any */
import { useQuery } from '@tanstack/react-query';

interface IArbitrageSummary {
  pausePositionSync?: string;
  spread?: number;
  pairStatus?: string;
  entryAction?: string;
  entryMarkPrice?: number;
  hedgeMarkPrice?: number;
  entryPrice?: number;
  hedgePrice?: number;
  entrySize?: number;
  hedgeSize?: number;
  hedgeAction?: string;
  unrealizedTotal?: number;
  time_update_hedge?: string;
  time_update_entry?: string;
  netExpose?: number;
  netExposeAction?: string;
  entrySymbol?: string;
  hedgeSymbol?: string;
  price_diff_percent?: number;
  gridBotStatus?: string;
  current_upper_diff?: number;
  current_lower_diff?: number;
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
        gridBotStatus = 'Active',
        spread = 0,
        pairStatus = 'Idle',
        entryAction = 'N/A',
        entryMarkPrice = 0,
        hedgeMarkPrice = 0,
        entryPrice = 0,
        hedgePrice = 0,
        entrySize = 0,
        hedgeSize = 0,
        hedgeAction = 'N/A',
        unrealizedTotal = 0,
        time_update_hedge = '-',
        time_update_entry = '-',
        netExpose = 0,
        netExposeAction = 'Safe',
        entrySymbol = 'default',
        hedgeSymbol = 'default',
        price_diff_percent = 0.0,
        current_upper_diff = undefined,
        current_lower_diff = undefined,
    } = (arbitrageSummary || {}) as IArbitrageSummary;

    return { 
        isLoading,
        pausePositionSync,
        gridBotStatus,
        spread,
        pairStatus,
        entryAction,
        entryMarkPrice,
        hedgeMarkPrice,
        entryPrice,
        hedgePrice,
        entrySize,
        hedgeSize,
        hedgeAction,
        unrealizedTotal,
        time_update_hedge,
        time_update_entry,
        netExpose,
        netExposeAction,
        entrySymbol,
        hedgeSymbol,
        price_diff_percent,
        current_upper_diff,
        current_lower_diff
     }
}
