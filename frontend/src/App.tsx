import "./App.css";
import PausePositionBtn from "./components/pause-btn";

// todo: add fetch data (react-query)
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
  } = initialData; // ใช้ค่าเริ่มต้นก่อน หรือใช้ useState()

  return (
    <>
      <div className="max-w-4xl mx-auto">
        <h1 className="text-3xl font-bold text-gray-800 mb-6">
          Arbitrage Bot Health Status
        </h1>

        <PausePositionBtn />

        <p id="bot-sync-status-display" className="text-lg font-medium">
          Bot sync status:{" "}
          <span
            className={`font-bold ${
              pausePositionSync === "Active"
                ? "text-green-600"
                : "text-gray-500"
            }`}
          >
            {pausePositionSync}
          </span>
        </p>

        {/* Price Watch Channel Card */}
        <div className="card bg-white p-6 rounded-xl shadow-lg mb-6 border-blue-500">
          <h2 className="text-xl font-semibold text-blue-700 mb-4">
            Price Watch Channel
          </h2>
          <div className="space-y-3 text-gray-700">
            <p className="text-lg">
              Binance (PAXG):
              <span className="font-mono text-blue-600 font-bold ml-2">
                {binanceMarkPrice}
              </span>
            </p>
            <p className="text-lg">
              MT5 (XAU):
              <span className="font-mono text-green-600 font-bold ml-2">
                {mt5MarkPrice}
              </span>
            </p>
            <p className="text-xl font-bold mt-4">
              Spread (Gap):
              <span
                className={`font-mono ml-2 ${
                  spread > 0 ? "text-green-500" : "text-red-500"
                }`}
              >
                {spread}
              </span>
            </p>
          </div>
        </div>

        {/* Matched Pairs Card */}
        <div className="card bg-white p-6 rounded-xl shadow-lg mb-6 border-yellow-500">
          <h2 className="text-xl font-semibold text-yellow-700 mb-4">
            Matched Pairs (Current Position)
          </h2>
          <div className="space-y-3 text-gray-700">
            <p>
              Status:{" "}
              <span
                className={`font-semibold text-gray-900 ${
                  pairStatus === "Warning" ? "text-red-600" : "text-green-600"
                }`}
              >
                {pairStatus}
              </span>
            </p>
            <p>
              Binance:
              <span
                className={`font-mono font-medium ${
                  binanceAction === "LONG"
                    ? "text-green-600"
                    : binanceAction === "SHORT"
                    ? "text-red-600"
                    : "text-gray-500"
                }`}
              >
                {binanceAction}
              </span>
              <span
                className={`font-mono font-bold ${
                  binanceSize > 0 ? "text-green-600" : "text-red-600"
                }`}
              >
                {binanceSize}
              </span>
              PAXG @{" "}
              <span className="font-mono">
                {binanceMarkPrice} ({time_update_binance})
              </span>
            </p>

            <p>
              Mt5:
              <span
                className={`font-mono font-medium 
                    ${
                      mt5Action === "LONG"
                        ? "text-green-600"
                        : mt5Action === "SHORT"
                        ? "text-red-600"
                        : "text-gray-500"
                    }`}
              >
                '{mt5Action}'
              </span>
              <span
                className={`font-mono font-bold
                  ${mt5Size > 0 ? "text-green-600" : "text-red-600"}
                   `}
              >
                {mt5Size}
              </span>
              XAU @{" "}
              <span className="font-mono">
                {mt5MarkPrice} ({time_update_mt5})
              </span>
            </p>

            <p>
              PNL (Unrealized):
              <span
                className={`font-mono text-lg font-bold ${
                  unrealizedBinance >= 0 ? "text-green-500" : "text-red-500"
                }`}
              >
                {unrealizedBinance} USD
              </span>
            </p>
          </div>
        </div>

        <div className="card bg-white p-6 rounded-xl shadow-lg border-green-500">
          <h2 className="text-xl font-semibold text-green-700 mb-4">Summary</h2>
          <div className="space-y-3 text-gray-700">
            <p>
              Total PAXG:{" "}
              <span
                className={`font-mono font-medium 
                    ${binanceSize > 0 ? "text-green-600" : "text-red-600"}`}
              >
                {binanceSize}
              </span>
            </p>

            <p>
              Total XAU Lots:{" "}
              <span
                className={`font-mono font-medium
                    ${mt5Size > 0 ? "text-green-600" : "text-red-600"} 
                    `}
              >
                {mt5Size}
              </span>
            </p>
            <p>
              Net Expose:{" "}
              <span className="font-mono font-medium text-gray-500">
                {netExpose} ({netExposeAction})
              </span>
            </p>
          </div>
        </div>
      </div>
    </>
  );
}

export default App;
