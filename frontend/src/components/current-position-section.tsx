import { useGetActiveUser } from "../hooks/active-user";
import { useGetSummaryStreamData } from "../hooks/summary";
import type { ICardSection } from "../interfaces/control-panel.interface";
import type { IPairDetails } from "../interfaces/current-position.interface";

const PairDetails = (arg: IPairDetails) => {
  const {
    pairStatus,
    entryAction,
    entrySize,
    entrySymbol,
    time_update_entry,
    hedgeAction,
    hedgeSize,
    hedgeSymbol,
    time_update_hedge,
    entryPrice,
    hedgePrice,
    unrealizedTotal,
    ask_diff,
    bid_diff
  } = arg
  
  const dataRows = [
    { 
      label: 'Status', 
      value: pairStatus, 
      valueClass: pairStatus === 'Warning' ? 'text-red-600 font-bold' : 'text-green-600 font-bold' 
    },
    { 
      label: 'Entry Position Info', 
      value: `${entryAction} ${entrySize} ${entrySymbol}`, 
      subValue: `(${time_update_entry})` 
    },
    { 
      label: 'Hedge Position Info', 
      value: `${hedgeAction} ${hedgeSize} ${hedgeSymbol}`, 
      subValue: `(${time_update_hedge})` 
    },
    {
      label: 'Ask Diff',
      value: `${ask_diff !== undefined ? ask_diff.toFixed(2) : 0.00}`,
      valueClass: ask_diff !== undefined ? (ask_diff > 0 ? 'text-green-500' : 'text-red-500') : 'text-gray-400'
    },
    {
      label: 'Bid Diff',
      value: `${bid_diff !== undefined ? bid_diff.toFixed(2) : 0.00}`,
      valueClass: bid_diff !== undefined ? (bid_diff > 0 ? 'text-green-500' : 'text-red-500') : 'text-gray-400'
    },
    { 
      label: 'Entry Price', 
      value: entryPrice ? entryPrice.toFixed(2) : 0.00 
    },
    { 
      label: 'Hedge Price', 
      value: hedgePrice ? hedgePrice.toFixed(2) : 0.00 
    },
    { 
      label: 'Price Diff', 
      value: (entryPrice && hedgePrice) ? (entryPrice - hedgePrice).toFixed(2) : 0.00,
      valueClass: 'font-mono'
    },
    { 
      label: 'PNL', 
      value: `${unrealizedTotal ? unrealizedTotal.toFixed(2) : 0.00} USD`, 
      valueClass: (unrealizedTotal && unrealizedTotal >= 0) ? 'text-green-500 font-bold' : 'text-red-500 font-bold' 
    }
  ];

  return (
    <div className="bg-white dark:bg-gray-700/50 p-4 rounded-lg shadow-sm border border-gray-100 dark:border-gray-600 max-w-md w-full">
      <ul className="divide-y divide-gray-100 dark:divide-gray-600">
        {dataRows.map((row, index) => (
          <li key={index} className="py-2.5 flex justify-between items-start text-sm">
            <span className="text-gray-500 dark:text-gray-400 font-medium">{row.label}</span>
            <div className="text-right">
              <span className={`block ${row.valueClass || 'text-gray-900 dark:text-gray-100'}`}>
                {row.value}
              </span>
              {row.subValue && (
                <span className="text-[10px] text-gray-400 dark:text-gray-500 block mt-0.5 uppercase">
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
          entryAction,
          entrySize,
          entrySymbol,
          time_update_entry,
          hedgeAction,
          hedgeSize,
          hedgeSymbol,
          time_update_hedge,
          entryPrice,
          hedgePrice,
          unrealizedTotal,
          ask_diff,
          bid_diff
        } = useGetSummaryStreamData(apiUrl)
        const { activeUser } = useGetActiveUser(apiUrl)
        const input_pair_data: IPairDetails = {
          pairStatus,
          entryAction,
          entrySize,
          entrySymbol,
          time_update_entry,
          hedgeAction,
          hedgeSize,
          hedgeSymbol,
          time_update_hedge,
          entryPrice,
          hedgePrice,
          unrealizedTotal,
          ask_diff,
          bid_diff
        }

    if (isLoading) {
        return <div className="flex justify-center mt-20 font-medium text-gray-600">Current Position: Connecting to API...</div>;
    }
    return (
        <div className="w-full max-w-md">
            <h2 className="text-sm font-bold mb-3 text-gray-800 dark:text-gray-100">
                {activeUser?.name}
            </h2>
            <PairDetails {...input_pair_data} />
        </div>
    )
}