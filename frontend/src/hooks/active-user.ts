import { useQuery } from "@tanstack/react-query"
import { getActiveUserInfo } from "../query/apis"

export const useGetActiveUser = (url: string) => {
    const { data: activeUser, error } = useQuery({
        queryKey: ['activeUser', url],
        queryFn: async () => {
        const response = await getActiveUserInfo(url)
        const json = await response.json()

        return {
            login: json.login,
            name: json.name,
            server: json.server,
            binance_account_name: json.binance_account_name,
            account_trade_allowed: json.account_trade_allowed,
            account_trade_expert: json.account_trade_expert,
            terminal_trade_allowed: json.terminal_trade_allowed,
            margin_level: json.margin_level,
            margin_so_call: json.margin_so_call,
            margin_so_so: json.margin_so_so,
            equity: json.equity,
            balance: json.balance,
            credit: json.credit
        }
        },
    })

    return { activeUser, error }
}