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
            binance_account_name: json.binance_account_name
        }
        },
    })

    return { activeUser, error }
}