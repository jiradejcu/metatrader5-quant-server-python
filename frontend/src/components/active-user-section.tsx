import { useGetActiveUser } from "../hooks/active-user";
import type { ICardSection } from "../interfaces/control-panel.interface";

export const ActiveUserSection = (arg: ICardSection) => {
    const {
        apiUrl,
    } = arg

    const { activeUser } = useGetActiveUser(apiUrl)
    
    if (!activeUser) {
        return <div className="flex justify-center mt-20 font-medium text-gray-600">Active User: Connecting to API...</div>;
    }
    return (
        <>
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
        </>
    )
}