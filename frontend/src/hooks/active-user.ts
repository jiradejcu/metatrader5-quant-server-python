import { useQuery } from "@tanstack/react-query"
import { getActiveUserInfo } from "../query/apis"

export const useGetActiveUser = (url: string) => {
    const { data: activeUser } = useQuery({
        queryKey: ['activeUser', url],
        queryFn: async () => {
        const response = await getActiveUserInfo(url)
        const json = await response.json()

        return {
            binance_key: json.binance_key,
            login: json.login,
            name: json.name,
            server: json.server,
            binance_account_name: json.binance_account_name
        }
        },
    })

    return { activeUser }
}