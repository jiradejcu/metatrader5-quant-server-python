/* eslint-disable @typescript-eslint/no-explicit-any */
import "./App.css";
import { useQuery } from '@tanstack/react-query';
import { getArbitrageSummary } from './query/apis';

const initialData = {
  binanceMarkPrice: 0,
  mt5MarkPrice: 0,
  spread: 0,
  pairStatus: "Complete",
  binanceSize: 0,
  binanceAction: "NO POSITION",
  mt5Size: 0,
  netExpose: 0,
  netExposeAction: "Safe",
  mt5Action: "NO POSITION",
  unrealizedBinance: 0,
  pausePositionSync: "Active",
  time_update_mt5: "No Update",
  time_update_binance: "No Update",
};

function App() {
  const { data, isLoading, isError } = useQuery({
    queryKey: ['arbitrageSummary'],
    queryFn: async () => {
      const response = await getArbitrageSummary();
      // convert to json because we do not use axios
      const json = await response.json(); 

      const botData = json.data; 

      // Sanitize data
      return {
        ...botData,
        binanceMarkPrice: Number(botData.binanceMarkPrice),
        mt5MarkPrice: Number(botData.mt5MarkPrice),
        spread: Number(botData.spread),
        unrealizedBinance: Number(botData.unrealizedBinance),
        binanceSize: Number(botData.binanceSize),
        mt5Size: Number(botData.mt5Size),
        netExpose: Number(botData.netExpose),
      } as any;
    },
    // refetchInterval: 5000,
    placeholderData: initialData,
  });

  const {
    pausePositionSync,
    spread,
    pairStatus,
    binanceAction,
    binanceMarkPrice,
    mt5MarkPrice,
    binanceSize,
    mt5Size,
    mt5Action,
    unrealizedBinance,
    time_update_mt5,
    time_update_binance,
    netExpose,
    netExposeAction,
  } = data;

  if (isLoading && !data) {
    return <div className="flex justify-center mt-20 font-medium">Connecting to Bot...</div>;
  }

  if (isError) {
    return <div className="text-center mt-20 text-red-500 font-bold">Failed to connect to API</div>;
  }

  return (
    <div className="max-w-4xl mx-auto p-6">
      <header className="flex justify-between items-center mb-8">
        <h1 className="text-3xl font-bold text-gray-800">
          Arbitrage Bot Health Status
        </h1>
        <div className="flex items-center bg-gray-100 px-3 py-1 rounded-full">
          <span className="relative flex h-2 w-2 mr-2">
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-green-400 opacity-75"></span>
            <span className="relative inline-flex rounded-full h-2 w-2 bg-green-500"></span>
          </span>
          <span className="text-xs font-medium text-gray-600">LIVE</span>
        </div>
      </header>

      <div className="mb-6">
        <p className="text-lg font-medium">
          Bot sync status:{" "}
          <span className={`font-bold ${pausePositionSync === "Active" ? "text-green-600" : "text-gray-400"}`}>
            {pausePositionSync}
          </span>
        </p>
      </div>

      <section className="grid gap-6">
        {/* Price Watch Card */}
        <div className="bg-white p-6 rounded-xl shadow-md border-l-4 border-blue-500">
          <h2 className="text-xl font-semibold text-blue-700 mb-4">Price Watch</h2>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <p className="text-sm text-gray-500 uppercase">Binance (PAXG)</p>
              <p className="text-2xl font-mono font-bold text-gray-800">{binanceMarkPrice?.toLocaleString()}</p>
            </div>
            <div>
              <p className="text-sm text-gray-500 uppercase">MT5 (XAU)</p>
              <p className="text-2xl font-mono font-bold text-gray-800">{mt5MarkPrice?.toLocaleString()}</p>
            </div>
          </div>
          <div className="mt-4 pt-4 border-t border-gray-100">
            <p className="text-lg font-bold">
              Spread: <span className={spread > 0 ? "text-green-500" : "text-red-500"}>{spread?.toFixed(2)}</span>
            </p>
          </div>
        </div>

        {/* Positions Card */}
        <div className="bg-white p-6 rounded-xl shadow-md border-l-4 border-yellow-500">
          <h2 className="text-xl font-semibold text-yellow-700 mb-4">Current Positions</h2>
          <p className="mb-4">Status: <span className={pairStatus === "Warning" ? "text-red-600 font-bold" : "text-green-600 font-bold"}>{pairStatus}</span></p>
          
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-4">
            <div className="bg-gray-50 p-4 rounded-lg">
              <p className="text-xs font-bold text-gray-400 mb-1">BINANCE</p>
              <p className={`text-lg font-bold ${binanceAction === 'LONG' ? 'text-green-600' : 'text-red-600'}`}>
                {binanceAction} {binanceSize}
              </p>
              <p className="text-[10px] text-gray-400 mt-1">{time_update_binance}</p>
            </div>
            <div className="bg-gray-50 p-4 rounded-lg">
              <p className="text-xs font-bold text-gray-400 mb-1">MT5</p>
              <p className={`text-lg font-bold ${mt5Action === 'LONG' ? 'text-green-600' : 'text-red-600'}`}>
                {mt5Action} {mt5Size}
              </p>
              <p className="text-[10px] text-gray-400 mt-1">{time_update_mt5}</p>
            </div>
          </div>

          <p className="text-lg font-semibold">
            Unrealized PNL: <span className={unrealizedBinance >= 0 ? "text-green-500" : "text-red-500"}>{unrealizedBinance?.toFixed(2)} USD</span>
          </p>
        </div>

        {/* Summary Card */}
        <div className="bg-white p-6 rounded-xl shadow-md border-l-4 border-green-500">
          <h2 className="text-xl font-semibold text-green-700 mb-4">Risk Summary</h2>
          <div className="flex gap-12">
            <div>
              <p className="text-sm text-gray-500">Net Exposure</p>
              <p className="text-2xl font-mono font-bold">{netExpose}</p>
            </div>
            <div>
              <p className="text-sm text-gray-500">Action State</p>
              <p className={`text-2xl font-bold ${netExposeAction === 'Safe' ? 'text-green-600' : 'text-red-600'}`}>{netExposeAction}</p>
            </div>
          </div>
        </div>
      </section>
    </div>
  );
}

export default App;