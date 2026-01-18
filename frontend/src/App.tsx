/* eslint-disable @typescript-eslint/no-explicit-any */
import "./App.css";
import PausePositionBtn from "./components/pause-btn";
import RestartBotContainerBtn from "./components/restart-container-btn"
import StopBotContainerBtn from "./components/stop-container-btn";
import { useQuery } from '@tanstack/react-query';
import { getActiveUserInfo, getArbitrageSummary, getBotContainerStatus } from './query/apis';
import { SECOND } from "./constant/time";

function App() {
  const { data, isLoading } = useQuery({
    queryKey: ['arbitrageSummary'],
    queryFn: async () => {
      const response = await getArbitrageSummary();
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

  const { data: botServer } = useQuery({
    queryKey: ['botServerStatus'],
    queryFn: async ()  => {
      const response = await getBotContainerStatus()
      const json = await response.json()

      return {
        status: json.status
      }
    },
    staleTime: Infinity,
    refetchOnWindowFocus: false,
  })

  const { data: activeUser } = useQuery({
    queryKey: ['activeUser'],
    queryFn: async () => {
      const response = await getActiveUserInfo()
      const json = await response.json()

      return {
        binance_key: json.binance_key,
        login: json.login,
        name: json.name,
        server: json.server,
        binance_account_name: json.binance_account_name
      }
    },
    staleTime: Infinity,
    refetchOnWindowFocus: false,
  })

  const displayData = data || {};
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
  } = displayData;

  if (isLoading && !data) {
    return <div className="flex justify-center mt-20 font-medium text-gray-600">Connecting to Bot...</div>;
  }

  // Now using color theme Intellectual Nonchalance (https://hookagency.com/blog/website-color-schemes-2020/)
  return (
    <div className="p-4 sm:p-8 bg-[#f3f4f6] min-h-screen">
      <div className="max-w-4xl mx-auto">
        <h1 className="text-3xl font-bold text-gray-800 mb-6">Arbitrage Bot Health Status</h1>

        <section className="mt-6 grid gap-6">
            {/* Cards use standard styling from HTML template */}
            <div className="card bg-white p-6 rounded-xl shadow-lg border-l-4 border-[#e62739]">
                <h2 className="text-xl font-semibold text-[#e62739] mb-4">Control Channel</h2>
                <p className="text-lg font-medium">
                  Bot sync status: <span className={`font-bold ${pausePositionSync === 'Active' ? 'text-green-600' : 'text-gray-500'}`}>
                    {pausePositionSync}
                  </span>
                </p>
                <PausePositionBtn />
                
                <p className="text-lg fint-medium">
                  Bot server status: <span className="font-bold text-gray-500">
                    {botServer?.status ?? 'Fetching'}
                  </span>
                </p>
                <StopBotContainerBtn />

                <p>Press this button when position value lost.</p>
                <RestartBotContainerBtn />
            </div>
            <div className="card bg-white p-6 rounded-xl shadow-lg border-l-4 border-[#e1e8f0]">
                <h2 className="text-xl font-semibold text-[#CCDDF0] mb-4">Active User</h2>
                <div className="space-y-3">
                  <div className="relative group cursor-pointer">
                    <p data-tooltip-target="binance-account-name-tooltip" >Binance Holder: <span className="font-mono text-blue-600 font-bold ml-2">{activeUser?.binance_account_name}</span></p>
                    <div
                        className="absolute bottom-full left-1/2 
                       transform -translate-x-1/2 mb-2 
                       w-max px-2 py-1 text-sm text-white
                       bg-gray-700 rounded shadow-lg 
                       opacity-0 group-hover:opacity-100">
                        API Key: {activeUser?.binance_key}
                    </div>
                  </div>
                    
                  <p>MT5 Account: <span className="font-mono text-green-600 font-bold ml-2">{activeUser?.name} [{activeUser?.login}] | Server {activeUser?.server} </span></p>
                </div>
            </div>

            <div className="card bg-white p-6 rounded-xl shadow-lg border-l-4 border-[#9068be]">
                <h2 className="text-xl font-semibold text-[#9068be] mb-4">Price Watch Channel</h2>
                <div className="space-y-3">
                    <p>Binance (PAXG): <span className="font-mono text-blue-600 font-bold ml-2">{binanceMarkPrice.toFixed(2)}</span></p>
                    <p>MT5 (XAU): <span className="font-mono text-green-600 font-bold ml-2">{mt5MarkPrice.toFixed(2)}</span></p>
                    <p className="text-xl font-bold mt-4">Spread: <span className={spread > 0 ? 'text-green-500' : 'text-red-500'}>{spread.toFixed(2)}</span></p>
                </div>
            </div>

            <div className="card bg-white p-6 rounded-xl shadow-lg border-l-4 border-[#9068be]">
                <h2 className="text-xl font-semibold text-[#9068be] mb-4">Current Positions</h2>
                <div className="space-y-3">
                    <p>Status: <span className={pairStatus === 'Warning' ? 'text-red-600' : 'text-green-600'}>{pairStatus}</span></p>
                    <p>Binance: {binanceAction} {binanceSize} PAXG ({time_update_binance})</p>
                    <p>Mt5: {mt5Action} {mt5Size} XAU ({time_update_mt5})</p>
                    <p>Binance entry: {binanceEntry} ({time_update_binance})</p>
                    <p>Mt5 entry: {mt5Entry} ({time_update_mt5})</p>
                    <p>Entry Diff: {(binanceEntry-mt5Entry).toFixed(2)}</p>
                    <p>PNL: <span className={unrealizedBinance >= 0 ? 'text-green-500' : 'text-red-500'}>{unrealizedBinance.toFixed(2)} USD</span></p>
                </div>
            </div>

            <div className="card bg-white p-6 rounded-xl shadow-lg border-l-4 border-[#6ed3cf]">
                <h2 className="text-xl font-semibold text-[#6ed3cf] mb-4">Summary</h2>
                <div className="space-y-3">
                    <p>Net Expose: {netExpose} ({netExposeAction})</p>
                </div>
            </div>
        </section>
      </div>
    </div>
  );
}

export default App;