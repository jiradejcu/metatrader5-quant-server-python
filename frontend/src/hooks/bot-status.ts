import { useQuery } from "@tanstack/react-query"
import { getBotContainerStatus } from "../query/apis"

export const useGetBotStatus = (url: string) => {
    const { data: botServer } = useQuery({
        queryKey: ['botServerStatus', url],
        queryFn: async ()  => {
        const response = await getBotContainerStatus(url)
        const json = await response.json()

        return {
            status: json.status
        }
        },
    })

    return { botServer }
}