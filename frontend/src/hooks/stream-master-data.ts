import { useQuery, useQueryClient } from "@tanstack/react-query"
import { useEffect, useState } from "react";

export const useStreamQuantMaster = (url: string) => {
    const queryClient = useQueryClient()
    const queryKey = ['stream', 'quant', 'master']
    const [isConnected, setIsConnected] = useState(false)

    const { isLoading } = useQuery({
        queryKey,
        enabled: false,
    })

    useEffect(()=> {
        setIsConnected(false)

        // Browser Caching of the SSE Stream
        const eventSource = new EventSource(`${url}/stream/quants?t=${Date.now()}`);
        eventSource.onopen = () => {
            console.log(`SSE Connection with host ${url} Opened!`);
            setIsConnected(true);
        };

        eventSource.onmessage = (event) => {
            const parsed = JSON.parse(event.data);
            // Update Cache data
            queryClient.setQueryData(['grid', 'parameters', url], parsed.grid_data);
            queryClient.setQueryData(['arbitrage', 'summary', url], parsed.arbitrage_summary);
        };

        // Browser auto-retries the connection; surface the outage instead of
        // silently keeping the last cached (possibly "Active") status.
        eventSource.onerror = () => {
            console.error(`SSE Connection with host ${url} lost, retrying...`);
            setIsConnected(false);
        };

        // clear up on unmount
        return () => {
            eventSource.close();
        }
    }, [queryClient, url])

    return {
        isLoading,
        isConnected,
    }
}