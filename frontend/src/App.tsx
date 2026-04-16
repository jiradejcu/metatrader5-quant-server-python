/* eslint-disable @typescript-eslint/no-explicit-any */
import { useState } from "react";
import "./App.css";
import { ControlSection } from "./components/control-section";
import { ActiveUserSection } from "./components/active-user-section";
import { PriceWatchSection } from "./components/price-watch-section";
import { CurrentPositionSection } from "./components/current-position-section";
import { ExposureSection } from "./components/exposure-section";
import { useAllBots } from "./hooks/all-bot";

const BOT_LABELS = ["Bot 1", "Bot 2", "Bot 3"];

function BotView({ apiUrl }: { apiUrl: string }) {
  return (
    <div className="grid gap-3 sm:gap-5">
      {/* Control Channel */}
      <div className="bg-white dark:bg-gray-800 p-4 rounded-xl shadow border-l-4 border-[#e62739]">
        <h2 className="text-base font-semibold text-[#e62739] mb-3">Control Channel</h2>
        <div className="overflow-y-auto custom-scrollbar scrollbar-red">
          <ControlSection apiUrl={apiUrl} />
        </div>
      </div>

      {/* Active User */}
      <div className="bg-white dark:bg-gray-800 p-4 rounded-xl shadow border-l-4 border-[#37BCED]">
        <h2 className="text-base font-semibold text-[#37BCED] mb-3">Active User</h2>
        <ActiveUserSection apiUrl={apiUrl} />
      </div>

      {/* Price Watch */}
      <div className="bg-white dark:bg-gray-800 p-4 rounded-xl shadow border-l-4 border-[#A5FF47]">
        <h2 className="text-base font-semibold text-[#A5FF47] mb-3">Price Watch</h2>
        <PriceWatchSection apiUrl={apiUrl} />
      </div>

      {/* Current Positions */}
      <div className="bg-white dark:bg-gray-800 p-4 rounded-xl shadow border-l-4 border-[#9068be]">
        <h2 className="text-base font-semibold text-[#9068be] mb-3">Current Positions</h2>
        <div className="overflow-y-auto custom-scrollbar scrollbar-purple flex flex-col items-center">
          <CurrentPositionSection apiUrl={apiUrl} />
        </div>
        <div className="mt-3 p-1.5 bg-gray-50 dark:bg-gray-700/50 text-[10px] text-center text-gray-400 uppercase tracking-widest rounded">
          Live Monitor Mode
        </div>
      </div>

      {/* Summary */}
      <div className="bg-white dark:bg-gray-800 p-4 rounded-xl shadow border-l-4 border-[#6ed3cf]">
        <h2 className="text-base font-semibold text-[#6ed3cf] mb-3">Summary</h2>
        <ExposureSection apiUrl={apiUrl} />
      </div>
    </div>
  );
}

function App() {
  const [activeTab, setActiveTab] = useState(0);
  const { botUrl, botUrl2, botUrl3 } = useAllBots();
  const botUrls = [botUrl, botUrl2, botUrl3];

  return (
    <div className="px-3 py-3 sm:px-5 sm:py-5 bg-[#f3f4f6] dark:bg-gray-900 min-h-screen">
      <div className="max-w-xl mx-auto">
        <h1 className="text-base font-bold text-gray-700 dark:text-gray-200 mb-3">
          Arbitrage Bot Health Status
        </h1>

        {/* Tab Navigation */}
        <div className="flex bg-white dark:bg-gray-800 rounded-xl shadow p-1 mb-4 gap-1 sticky top-3 z-10">
          {BOT_LABELS.map((label, i) => (
            <button
              key={i}
              onClick={() => setActiveTab(i)}
              className={`flex-1 py-2.5 px-2 rounded-lg text-sm font-semibold transition-all duration-200 cursor-pointer ${
                activeTab === i
                  ? "bg-gray-800 dark:bg-gray-600 text-white shadow"
                  : "text-gray-500 dark:text-gray-400 hover:text-gray-800 dark:hover:text-gray-100 hover:bg-gray-100 dark:hover:bg-gray-700"
              }`}
            >
              {label}
            </button>
          ))}
        </div>

        {/* Active Bot Content */}
        <BotView apiUrl={botUrls[activeTab]} />
      </div>
    </div>
  );
}

export default App;
