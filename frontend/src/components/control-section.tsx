import { useGetActiveUser } from "../hooks/active-user";
import { useGetBotStatus } from "../hooks/bot-status";
import { useStreamQuantMaster } from "../hooks/stream-master-data";
import { useGetSummaryStreamData } from "../hooks/summary";
import type { ICardSection } from "../interfaces/control-panel.interface";
import { GridSettingModal } from "./grid-setting-modals";
import PausePositionBtn from "./pause-btn";
import RestartBotContainerBtn from "./restart-container-btn";
// import StopBotContainerBtn from "./stop-container-btn";

export const ControlSection = (arg: ICardSection) => {
    const {
        apiUrl,
    } = arg

    const { botServer } = useGetBotStatus(apiUrl)
    const { activeUser } = useGetActiveUser(apiUrl)
    const {isLoading: isLoadingStreamMaster } = useStreamQuantMaster(apiUrl)

    // Calling SSE hook to keep the data updated
    const { isLoading, pausePositionSync } = useGetSummaryStreamData(apiUrl)

    if (isLoadingStreamMaster) {
      return <div className="flex justify-center mt-20 font-medium text-gray-600">SSE Connection with host {apiUrl} ...</div>;
    }



    if (isLoading && !pausePositionSync) {
        return <div className="flex justify-center mt-20 font-medium text-gray-600">Control panel: Connecting to Bot...</div>;
    }

    return (
        <div>
            <h3 className="text-base font-semibold text-[#705A5A] dark:text-[#c49a9a] mb-4">{activeUser?.name}</h3>
            {/* grid parameter settings */}
            <GridSettingModal
              url={apiUrl}
            />

            <p className="text-sm font-medium text-gray-700 dark:text-gray-300">
                  Position sync bot status: <span className={`font-bold ${pausePositionSync === 'Active' ? 'text-green-600' : 'text-gray-500'}`}>
                    {pausePositionSync}
                  </span>
                </p>
                <PausePositionBtn
                  url={apiUrl}
                />

                <p className="text-sm font-medium text-gray-700 dark:text-gray-300">
                  Bot server status: <span className="font-bold text-gray-500 dark:text-gray-400">
                    {botServer?.status ?? 'Fetching'}
                  </span>
                </p>

                <p className="text-sm text-gray-600 dark:text-gray-400">Press this button when position value lost.</p>
                <RestartBotContainerBtn
                  url={apiUrl}
                />
        </div>
    )
}