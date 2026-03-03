import { useGetActiveUser } from "../hooks/active-user";
import { useGetSummaryStreamData } from "../hooks/summary";
import type { ICardSection } from "../interfaces/control-panel.interface";
import type { IPairDetails } from "../interfaces/current-position.interface";

const PairDetails = (arg: IPairDetails) => {
  const {
    pairStatus,
    binanceAction,
    binanceSize,
    binanceSymbol,
    time_update_binance,
    mt5Action,
    mt5Size,
    mt5Symbol,
    time_update_mt5,
    binanceEntry,
    mt5Entry,
    unrealizedBinance,
    current_upper_diff,
    current_lower_diff
  } = arg
  
  const dataRows = [
    { 
      label: 'Status', 
      value: pairStatus, 
      valueClass: pairStatus === 'Warning' ? 'text-red-600 font-bold' : 'text-green-600 font-bold' 
    },
    { 
      label: 'Binance', 
      value: `${binanceAction} ${binanceSize} ${binanceSymbol}`, 
      subValue: `(${time_update_binance})` 
    },
    { 
      label: 'MT5', 
      value: `${mt5Action} ${mt5Size} ${mt5Symbol}`, 
      subValue: `(${time_update_mt5})` 
    },
    {
      label: 'Current Upper Diff',
      value: `${current_upper_diff !== undefined ? current_upper_diff.toFixed(2) : 0.00}`,
      valueClass: current_upper_diff !== undefined ? (current_upper_diff > 0 ? 'text-green-500' : 'text-red-500') : 'text-gray-400'
    },
    {
      label: 'Current Lower Diff',
      value: `${current_lower_diff !== undefined ? current_lower_diff.toFixed(2) : 0.00}`,
      valueClass: current_lower_diff !== undefined ? (current_lower_diff > 0 ? 'text-green-500' : 'text-red-500') : 'text-gray-400'
    },
    { 
      label: 'Binance Entry', 
      value: binanceEntry ? binanceEntry.toFixed(2) : 0.00 
    },
    { 
      label: 'MT5 Entry', 
      value: mt5Entry ? mt5Entry.toFixed(2) : 0.00 
    },
    { 
      label: 'Entry Diff', 
      value: (binanceEntry && mt5Entry) ? (binanceEntry - mt5Entry).toFixed(2) : 0.00,
      valueClass: 'font-mono'
    },
    { 
      label: 'PNL', 
      value: `${unrealizedBinance ? unrealizedBinance.toFixed(2) : 0.00} USD`, 
      valueClass: (unrealizedBinance && unrealizedBinance >= 0) ? 'text-green-500 font-bold' : 'text-red-500 font-bold' 
    }
  ];

  return (
    <div className="bg-white p-4 rounded-lg shadow-sm border border-gray-100 max-w-md">
      <ul className="divide-y divide-gray-100">
        {dataRows.map((row, index) => (
          <li key={index} className="py-2.5 flex justify-between items-start text-sm">
            <span className="text-gray-500 font-medium">{row.label}</span>
            <div className="text-right">
              <span className={`block ${row.valueClass || 'text-gray-900'}`}>
                {row.value}
              </span>
              {row.subValue && (
                <span className="text-[10px] text-gray-400 block mt-0.5 uppercase">
                  {row.subValue}
                </span>
              )}
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}

export const CurrentPositionSection = (arg: ICardSection) => {
    const { apiUrl } = arg
        const { 
          isLoading,
          pairStatus,
          binanceAction,
          binanceSize,
          binanceSymbol,
          time_update_binance,
          mt5Action,
          mt5Size,
          mt5Symbol,
          time_update_mt5,
          binanceEntry,
          mt5Entry,
          unrealizedBinance,
          current_upper_diff,
          current_lower_diff
        } = useGetSummaryStreamData(apiUrl)
        const { activeUser } = useGetActiveUser(apiUrl)
        const input_pair_data: IPairDetails = {
          pairStatus,
          binanceAction,
          binanceSize,
          binanceSymbol,
          time_update_binance,
          mt5Action,
          mt5Size,
          mt5Symbol,
          time_update_mt5,
          binanceEntry,
          mt5Entry,
          unrealizedBinance,
          current_upper_diff,
          current_lower_diff
        }

    if (isLoading) {
        return <div className="flex justify-center mt-20 font-medium text-gray-600">Current Position: Connecting to API...</div>;
    }
    return (
        <div className="w-full max-w-md">
            <h2 className="text-lg font-bold mb-4">
                {activeUser?.name}
            </h2>
            <PairDetails {...input_pair_data} />
        </div>
    )
}