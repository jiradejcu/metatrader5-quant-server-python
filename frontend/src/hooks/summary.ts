/* eslint-disable @typescript-eslint/no-explicit-any */
import { useQuery } from '@tanstack/react-query';

interface IArbitrageSummary {
  pausePositionSync?: string;
  spread?: number;
  pairStatus?: string;
  binanceAction?: string;
  binanceMarkPrice?: number;
  mt5MarkPrice?: number;
  binanceEntry?: number;
  mt5Entry?: number;
  binanceSize?: number;
  mt5Size?: number;
  mt5Action?: string;
  unrealizedBinance?: number;
  time_update_mt5?: string;
  time_update_binance?: string;
  netExpose?: number;
  netExposeAction?: string;
  binanceSymbol?: string;
  mt5Symbol?: string;
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
        binanceAction = 'N/A',
        binanceMarkPrice = 0,
        mt5MarkPrice = 0,
        binanceEntry = 0,
        mt5Entry = 0,
        binanceSize = 0,
        mt5Size = 0,
        mt5Action = 'N/A',
        unrealizedBinance = 0,
        time_update_mt5 = '-',
        time_update_binance = '-',
        netExpose = 0,
        netExposeAction = 'Safe',
        binanceSymbol = 'default',
        mt5Symbol = 'default',
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
        binanceAction,
        binanceMarkPrice,
        mt5MarkPrice,
        binanceEntry,
        mt5Entry,
        binanceSize,
        mt5Size,
        mt5Action,
        unrealizedBinance,
        time_update_mt5,
        time_update_binance,
        netExpose,
        netExposeAction,
        binanceSymbol,
        mt5Symbol,
        price_diff_percent,
        current_upper_diff,
        current_lower_diff
     }
}
