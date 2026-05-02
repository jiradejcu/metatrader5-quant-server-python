import { useQuery } from "@tanstack/react-query";


interface IGridSettings {
    upper_limit: number;
    lower_limit: number;
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