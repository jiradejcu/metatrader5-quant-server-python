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
    const autoTradeOk = activeUser?.account_trade_expert && activeUser?.terminal_trade_allowed

    return (
        <>
            <p className="text-sm text-gray-600 dark:text-gray-400">Binance Holder: <span className="font-mono text-blue-600 dark:text-blue-400 font-bold ml-2">{activeUser?.binance_account_name}</span></p>

            <p className="text-sm text-gray-600 dark:text-gray-400 mt-1">MT5 Account: <span className="font-mono text-green-600 dark:text-green-400 font-bold ml-2">{activeUser?.name} [{activeUser?.login}] | Server {activeUser?.server} </span></p>

            <p className="text-sm text-gray-600 dark:text-gray-400 mt-1">
                Auto Trading: <span className={`font-mono font-bold ml-2 ${autoTradeOk ? 'text-green-600 dark:text-green-400' : 'text-red-500'}`}>
                    {autoTradeOk ? 'Allowed' : 'Blocked'}
                </span>
                <span className="ml-2 text-xs text-gray-500 dark:text-gray-500">
                    (terminal: {String(activeUser?.terminal_trade_allowed)}, server/EA: {String(activeUser?.account_trade_expert)})
                </span>
            </p>

            <p className="text-sm text-gray-600 dark:text-gray-400 mt-1">
                Margin Level: <span className={`font-mono font-bold ml-2 ${
                    activeUser?.margin_level != null && activeUser?.margin_so_so != null && activeUser.margin_level <= activeUser.margin_so_so
                        ? 'text-red-500'
                        : 'text-gray-800 dark:text-gray-200'
                }`}>
                    {activeUser?.margin_level != null ? `${activeUser.margin_level.toFixed(1)}%` : '—'}
                </span>
                <span className="ml-2 text-xs text-gray-500 dark:text-gray-500">
                    (stop out at {activeUser?.margin_so_so ?? '—'}%, equity {activeUser?.equity ?? '—'}, balance {activeUser?.balance ?? '—'})
                </span>
            </p>
        </>
    )
}