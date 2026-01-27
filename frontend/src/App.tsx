/* eslint-disable @typescript-eslint/no-explicit-any */
import "./App.css";
import { ControlSection } from "./components/control-section";
import { ActiveUserSection } from "./components/active-user-section";
import { PriceWatchSection } from "./components/price-watch-section";
import { CurrentPositionSection } from "./components/current-position-section";
import { ExposureSection } from "./components/exposure-section";
import { useAllBots } from "./hooks/all-bot";

function App() {
  const { 
    botUrl,
    botUrl2,
    botUrl3
  } = useAllBots()
  // Now using color theme Intellectual Nonchalance (https://hookagency.com/blog/website-color-schemes-2020/)
  return (
    <div className="p-4 sm:p-8 bg-[#f3f4f6] min-h-screen">
      <div className="max-w-4xl mx-auto">
        <h1 className="text-2xl font-bold text-gray-800 mb-6">Arbitrage Bot Health Status</h1>

        <section className="mt-6 grid gap-6">
            {/* Cards use standard styling from HTML template */}
            <div className="card bg-white p-6 rounded-xl shadow-lg border-l-4 border-[#e62739] flex flex-col max-w-3xl max-h-[500px]">
                <h2 className="text-xl font-semibold text-[#e62739] mb-4">Control Channel</h2>
                <div className="p-6 pt-2 overflow-y-auto custom-scrollbar scrollbar-red space-y-4">
                  <ControlSection
                  apiUrl={botUrl}
                  />
                  <ControlSection
                    apiUrl={botUrl2}
                  />
                  <ControlSection
                    apiUrl={botUrl3}
                  />
                </div>
            </div>


            <div className="card bg-white p-6 rounded-xl shadow-lg border-l-4 border-[#37BCED] flex flex-col max-w-3xl max-h-[200px]">
                <h2 className="text-xl font-semibold text-[#37BCED] mb-4">Active User</h2>
                <div className="p-6 pt-2 overflow-y-auto custom-scrollbar scrollbar-blue space-y-4">
                  <ActiveUserSection
                    apiUrl={botUrl} 
                  />
                  <ActiveUserSection
                    apiUrl={botUrl2} 
                  />
                  <ActiveUserSection
                    apiUrl={botUrl3} 
                  />
                </div>
            </div>

            <div className="card bg-white p-6 rounded-xl shadow-lg border-l-4 border-[#A5FF47] flex flex-col max-w-3xl max-h-[340px]">
                <h2 className="text-xl font-semibold text-[#A5FF47] mb-4">Price Watch Channel</h2>
                <div className="p-6 pt-2 overflow-y-auto custom-scrollbar scrollbar-green space-y-4">
                    <PriceWatchSection 
                      apiUrl={botUrl} 
                    />
                    <PriceWatchSection 
                      apiUrl={botUrl2} 
                    />
                    <PriceWatchSection 
                      apiUrl={botUrl3} 
                    />
                </div>
            </div>
            
            <div className="card bg-white p-6 rounded-xl shadow-lg border-l-4 border-[#9068be] flex flex-col w-full max-w-3xl mx-auto overflow-hidden h-[500px]">
                <h2 className="text-xl font-semibold text-[#9068be] mb-4">Current Positions</h2>

                {/* Scrollable Container */}
                <div className="flex-1 overflow-y-auto custom-scrollbar scrollbar-purple p-6 flex flex-col items-center space-y-8">
                    <CurrentPositionSection 
                      apiUrl={botUrl}
                    />
                    <CurrentPositionSection 
                      apiUrl={botUrl2}
                    />
                    <CurrentPositionSection 
                        apiUrl={botUrl3}
                    />
                </div>

                {/* ตกแต่ง Footer */}
                <div className="p-3 bg-gray-50 text-[10px] text-center text-gray-400 uppercase tracking-widest">
                  Live Monitor Mode
                </div>
            </div>

            <div className="card bg-white p-6 rounded-xl shadow-lg border-l-4 border-[#6ed3cf] flex flex-col max-w-3xl max-h-[200px]">
              <div className="p-6 pt-2 overflow-y-auto custom-scrollbar scrollbar-cray space-y-4">
                <h2 className="text-xl font-semibold text-[#6ed3cf] mb-4">Summary</h2>
                <ExposureSection 
                  apiUrl={botUrl}
                />
                <ExposureSection 
                  apiUrl={botUrl2}
                />
                <ExposureSection 
                  apiUrl={botUrl3}
                />
              </div>
            </div>
        </section>
      </div>
    </div>
  );
}

export default App;