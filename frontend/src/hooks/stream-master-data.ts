import { useQuery, useQueryClient } from "@tanstack/react-query"
import { useEffect } from "react";

export const useStreamQuantMaster = (url: string) => {
    const queryClient = useQueryClient()
    const queryKey = ['stream', 'quant', 'master']

    const { isLoading } = useQuery({
        queryKey,
        enabled: false,
    })

    useEffect(()=> {
        // Browser Caching of the SSE Stream
        const eventSource = new EventSource(`${url}/stream/quants?t=${Date.now()}`);
        eventSource.onopen = () => console.log(`SSE Connection with host ${url} Opened!`);

        eventSource.onmessage = (event) => {
            const parsed = JSON.parse(event.data);
            // Update Cache data
            queryClient.setQueryData(['grid', 'parameters', url], parsed.grid_data);
            queryClient.setQueryData(['arbitrage', 'summary', url], parsed.arbitrage_summary);
        };

        // clear up on unmount
        return () => {
            eventSource.close(); 
        }
    }, [queryClient, url])

    return {
        isLoading,
    }
}