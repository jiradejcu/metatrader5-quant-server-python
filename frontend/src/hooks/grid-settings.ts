import { useQuery } from "@tanstack/react-query";


interface IGridSettings {
    long_upper_limit: number;
    long_lower_limit: number;
    short_upper_limit: number;
    short_lower_limit: number;
    max_position_size: number;
    order_size: number;
    mark_price: number;
    time: string;
}

export const useGetGridSettingsStreamData = (url: string) => {
    const {
        data,
        isLoading
    } = useQuery<IGridSettings>({
        queryKey: ['grid', 'parameters', url],
        enabled: false,
        staleTime: Infinity,
    })

    return {
        data,
        isLoading
    }
}