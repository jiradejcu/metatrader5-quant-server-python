/* eslint-disable @typescript-eslint/no-explicit-any */
import { useQuery } from '@tanstack/react-query';
import { SECOND } from '../constant/time';
import { getArbitrageSummary } from '../query/apis';

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
        mt5Symbol = 'default'
    } = displayData;

    return { 
        isLoading, 
        pausePositionSync,
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
        mt5Symbol
     }
}
