import { useGetActiveUser } from "../hooks/active-user";
import { useGetSummaryDataHook } from "../hooks/summary";
import type { ICardSection } from "../interfaces/control-panel.interface";

export const ExposureSection = (arg: ICardSection) => {
    const { apiUrl } = arg
    const {
        netExpose,
        netExposeAction,
        isLoading
    } = useGetSummaryDataHook(apiUrl)
    const { activeUser } = useGetActiveUser(apiUrl)
    
    if (isLoading) {
        return <div className="flex justify-center mt-20 font-medium text-gray-600">Exposure: Connecting to API...</div>;
    }
    return (
        <>
            <h3>{activeUser?.name}</h3>
            <p>Net Expose: {netExpose} ({netExposeAction})</p>
        </>
    )
}