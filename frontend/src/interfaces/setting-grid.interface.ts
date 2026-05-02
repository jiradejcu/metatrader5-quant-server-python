export interface SettingGridProps {
    upper_limit: number
    lower_limit: number
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