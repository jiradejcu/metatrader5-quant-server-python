import { useGetActiveUser } from "../hooks/active-user";
import type { ICardSection } from "../interfaces/control-panel.interface";

export const ActiveUserSection = (arg: ICardSection) => {
    const {
        apiUrl,
    } = arg

    const { activeUser, error } = useGetActiveUser(apiUrl)

    if (error) {
        return <div className="flex justify-center mt-4 font-medium text-red-500">Error: {(error as Error).message}</div>;
    }

    if (!activeUser) {
        return <div className="flex justify-center mt-4 font-medium text-gray-600">Active User: Connecting to API...</div>;
    }
    return (
        <>
            <p className="text-sm text-gray-600 dark:text-gray-400">Binance Holder: <span className="font-mono text-blue-600 dark:text-blue-400 font-bold ml-2">{activeUser?.binance_account_name}</span></p>

            <p className="text-sm text-gray-600 dark:text-gray-400 mt-1">MT5 Account: <span className="font-mono text-green-600 dark:text-green-400 font-bold ml-2">{activeUser?.name} [{activeUser?.login}] | Server {activeUser?.server} </span></p>
        </>
    )
}