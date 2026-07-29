import { useGetActiveUser } from "../hooks/active-user";
import { useGetBotStatus } from "../hooks/bot-status";
import { useStreamQuantMaster } from "../hooks/stream-master-data";
import { useGetSummaryStreamData } from "../hooks/summary";
import type { ICardSection } from "../interfaces/control-panel.interface";
import { GridSettingModal } from "./grid-setting-modals";
import { PredictionSettingModal } from "./prediction-setting-modal";
import { TradingSessionsModal } from "./trading-sessions-modal";
import PausePositionBtn from "./pause-btn";
import RestartBotContainerBtn from "./restart-container-btn";
// import StopBotContainerBtn from "./stop-container-btn";

const CONTAINER_STATUS_BAD = new Set(['exited', 'dead', 'error']);

function containerStatusColor(status: string | undefined): string {
    if (!status) return 'text-gray-500 dark:text-gray-400';
    if (status === 'running') return 'text-green-600';
    if (CONTAINER_STATUS_BAD.has(status)) return 'text-red-600';
    return 'text-gray-500 dark:text-gray-400';
}

function containerStatusLabel(status: string | undefined): string {
    if (!status) return 'Fetching';
    return status.charAt(0).toUpperCase() + status.slice(1);
}

export const ControlSection = (arg: ICardSection) => {
    const {
        apiUrl,
    } = arg

    const { botServer } = useGetBotStatus(apiUrl)
    const { activeUser } = useGetActiveUser(apiUrl)
    const {isLoading: isLoadingStreamMaster } = useStreamQuantMaster(apiUrl)

    // Calling SSE hook to keep the data updated
    const { isLoading, pausePositionSync, gridBotStatus, predictionBotStatus } = useGetSummaryStreamData(apiUrl)

    if (isLoadingStreamMaster) {
      return <div className="flex justify-center mt-20 font-medium text-gray-600">SSE Connection with host {apiUrl} ...</div>;
    }



    if (isLoading && !pausePositionSync) {
        return <div className="flex justify-center mt-20 font-medium text-gray-600">Control panel: Connecting to Bot...</div>;
    }

    return (
        <div>
            <h3 className="text-base font-semibold text-[#705A5A] dark:text-[#c49a9a] mb-4">{activeUser?.name}</h3>
            {/* grid + prediction bot settings */}
            <div className="flex gap-3 mb-4">
              <GridSettingModal
                url={apiUrl}
              />

              <PredictionSettingModal
                url={apiUrl}
              />
            </div>

            {/* trading session schedule */}
            <TradingSessionsModal
              url={apiUrl}
            />

            <p className="text-sm font-medium text-gray-700 dark:text-gray-300">
                  Grid bot status: <span className={`font-bold ${gridBotStatus === 'Active' ? 'text-green-600' : 'text-gray-500'}`}>
                    {gridBotStatus}
                  </span>
                </p>

                <p className="text-sm font-medium text-gray-700 dark:text-gray-300">
                  Prediction bot status: <span className={`font-bold ${predictionBotStatus === 'Active' ? 'text-green-600' : 'text-gray-500'}`}>
                    {predictionBotStatus}
                  </span>
                </p>

                <p className="text-sm font-medium text-gray-700 dark:text-gray-300">
                  Position sync bot status: <span className={`font-bold ${pausePositionSync === 'Active' ? 'text-green-600' : 'text-gray-500'}`}>
                    {pausePositionSync}
                  </span>
                </p>
                <PausePositionBtn
                  url={apiUrl}
                />

                <p className="text-sm font-medium text-gray-700 dark:text-gray-300">
                  Container status: <span className={`font-bold ${containerStatusColor(botServer?.status)}`}>
                    {containerStatusLabel(botServer?.status)}
                  </span>
                </p>

                <RestartBotContainerBtn
                  url={apiUrl}
                />
        </div>
    )
}