/* eslint-disable @typescript-eslint/no-explicit-any */
import { useQuery } from '@tanstack/react-query';
import { SECOND } from '../constant/time';
import { getArbitrageSummary } from '../query/apis';

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
}

export const useGetSummaryDataHook = (url: string) => {
    const { data, isLoading } = useQuery({
        queryKey: ['arbitrageSummary', url],
        queryFn: async () => {
          const response = await getArbitrageSummary(url);
          const json = await response.json(); 
          const botData = json.data; 
    
          return {
            ...botData,
            // Ensure values are numbers for styling logic
            binanceMarkPrice: Number(botData.binanceMarkPrice),
            mt5MarkPrice: Number(botData.mt5MarkPrice),
            binanceEntry: Number(botData.binanceEntry),
            mt5Entry: Number(botData.mt5Entry),
            spread: Number(botData.spread),
            unrealizedBinance: Number(botData.unrealizedBinance),
            binanceSize: Number(botData.binanceSize),
            mt5Size: Number(botData.mt5Size),
            netExpose: Number(botData.netExpose),
          } as any;
        },
        refetchInterval: SECOND,
      }); 

    const displayData = data || {};

    // Destructuring and set dafault values
    const {
        pausePositionSync = 'Active',
        gridBotStatus= 'Active',
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
        price_diff_percent = 0.0
    } = displayData;

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
        price_diff_percent
     }
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
        price_diff_percent = 0.0
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
        price_diff_percent
     }
}
