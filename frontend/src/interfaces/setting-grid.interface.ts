export interface SettingGridProps {
    long_upper_limit: number
    long_lower_limit: number
    short_upper_limit: number
    short_lower_limit: number
    max_position_size: number
    order_size: number
}

export interface IFloatingLabelInputProps {
    label: string;
    name: string;
    value: number | string;
    onChange: (e: React.ChangeEvent<HTMLInputElement>) => void;
    step?: string;
}