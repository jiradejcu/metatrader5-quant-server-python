import { useGetActiveUser } from "../hooks/active-user";
import { useGetBotStatus } from "../hooks/bot-status";
import { useGetSummaryDataHook } from "../hooks/summary";
import type { ICardSection } from "../interfaces/control-panel.interface";
import PausePositionBtn from "./pause-btn";
import RestartBotContainerBtn from "./restart-container-btn";
import StopBotContainerBtn from "./stop-container-btn";

export const ControlSection = (arg: ICardSection) => {
    const {
        apiUrl,
    } = arg

    const { botServer } = useGetBotStatus(apiUrl)
    const { activeUser } = useGetActiveUser(apiUrl)
    const { isLoading , pausePositionSync } = useGetSummaryDataHook(apiUrl)

    if (isLoading && !pausePositionSync) {
        return <div className="flex justify-center mt-20 font-medium text-gray-600">Control panel: Connecting to Bot...</div>;
    }

    return (
        <div>
            <h3 className="text-lg font-semibold text-[#705A5A] mb-4">{activeUser?.name}</h3>
            <p className="text-base font-medium">
                  Bot sync status: <span className={`font-bold ${pausePositionSync === 'Active' ? 'text-green-600' : 'text-gray-500'}`}>
                    {pausePositionSync}
                  </span>
                </p>
                <PausePositionBtn
                  url={apiUrl}
                />
                
                <p className="text-lg fint-medium">
                  Bot server status: <span className="font-bold text-gray-500">
                    {botServer?.status ?? 'Fetching'}
                  </span>
                </p>
                <StopBotContainerBtn 
                  url={apiUrl}
                />

                <p>Press this button when position value lost.</p>
                <RestartBotContainerBtn 
                  url={apiUrl}
                />

                <div className="h-10 bg-gray-25 rounded flex items-center justify-center text-xs text-gray-400 border border-dashed">
                  End of Pairs
                </div>
        </div>
    )
}