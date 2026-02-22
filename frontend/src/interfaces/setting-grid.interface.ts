export interface SettingGridProps {
    upper_diff: number
    lower_diff: number
    max_position_size: number
    order_size: number
    close_long: number
    close_short: number
}

export interface IFloatingLabelInputProps {
    label: string;
    name: string;
    value: number | string;
    onChange: (e: React.ChangeEvent<HTMLInputElement>) => void;
    step?: string;
}