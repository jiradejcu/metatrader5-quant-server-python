import { useGetActiveUser } from "../hooks/active-user";
import { useGetSummaryStreamData } from "../hooks/summary";
import type { ICardSection } from "../interfaces/control-panel.interface";

export const ExposureSection = (arg: ICardSection) => {
    const { apiUrl } = arg
    const { 
          isLoading,
          netExpose,
          netExposeAction
        } = useGetSummaryStreamData(apiUrl)
    const { activeUser } = useGetActiveUser(apiUrl)
    
    if (isLoading) {
        return <div className="flex justify-center mt-20 font-medium text-gray-600">Exposure: Connecting to API...</div>;
    }
    return (
        <>
            <h3 className="text-sm font-semibold text-gray-700 dark:text-gray-200 mb-1">{activeUser?.name}</h3>
            <p className="text-sm text-gray-600 dark:text-gray-400">Net Expose: {netExpose} ({netExposeAction})</p>
        </>
    )
}