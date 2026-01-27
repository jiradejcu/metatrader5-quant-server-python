import { useGetActiveUser } from "../hooks/active-user";
import { useGetSummaryDataHook } from "../hooks/summary";
import type { ICardSection } from "../interfaces/control-panel.interface";

const PairDetails = ({  
  pairStatus = 'Normal',
  binanceAction = 'None',
  binanceSize = '0.0',
  binanceSymbol = 'default',
  time_update_binance = '00:00:00',
  mt5Action = 'None',
  mt5Size = '0.0',
  mt5Symbol = 'None',
  time_update_mt5 = '00:00:00',
  binanceEntry = 0,
  mt5Entry = 0,
  unrealizedBinance = 0
}) => {
  
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
      label: 'Binance Entry', 
      value: binanceEntry.toFixed(4) 
    },
    { 
      label: 'MT5 Entry', 
      value: mt5Entry.toFixed(4) 
    },
    { 
      label: 'Entry Diff', 
      value: (binanceEntry - mt5Entry).toFixed(4),
      valueClass: 'font-mono'
    },
    { 
      label: 'PNL', 
      value: `${unrealizedBinance.toFixed(2)} USD`, 
      valueClass: unrealizedBinance >= 0 ? 'text-green-500 font-bold' : 'text-red-500 font-bold' 
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
            unrealizedBinance
         } = useGetSummaryDataHook(apiUrl)
        const { activeUser } = useGetActiveUser(apiUrl)

    if (isLoading) {
        return <div className="flex justify-center mt-20 font-medium text-gray-600">Current Position: Connecting to API...</div>;
    }
    return (
        <div className="w-full max-w-md">
            <h2 className="text-lg font-bold mb-4">
                {activeUser?.name}
            </h2>
            <PairDetails 
                pairStatus = {pairStatus}
                binanceAction = {binanceAction}
                binanceSize = {binanceSize}
                binanceSymbol = {binanceSymbol}
                time_update_binance = {time_update_binance}
                mt5Action = {mt5Action}
                mt5Size = {mt5Size}
                mt5Symbol = {mt5Symbol}
                time_update_mt5 = {time_update_mt5}
                binanceEntry = {binanceEntry}
                mt5Entry = {mt5Entry}
                unrealizedBinance = {unrealizedBinance}
            />
            {/* <p>Status: <span className={pairStatus === 'Warning' ? 'text-red-600' : 'text-green-600'}>{pairStatus}</span></p>
            <p>Binance: {binanceAction} {binanceSize} {binanceSymbol} ({time_update_binance})</p>
            <p>Mt5: {mt5Action} {mt5Size} {mt5Symbol} ({time_update_mt5})</p>
            <p>Binance entry: {binanceEntry.toFixed(4)}</p>
            <p>Mt5 entry: {mt5Entry}</p>
            <p>Entry Diff: {(binanceEntry-mt5Entry).toFixed(4)}</p>
            <p>PNL: <span className={unrealizedBinance >= 0 ? 'text-green-500' : 'text-red-500'}>{unrealizedBinance.toFixed(2)} USD</span></p> */}
        </div>
    )
}