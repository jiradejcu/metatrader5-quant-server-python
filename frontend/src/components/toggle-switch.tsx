interface ToggleSwitchProps {
  checked: boolean;
  onChange: () => void;
  disabled?: boolean;
  label?: string;
  labelClassName?: string;
}

export function ToggleSwitch({ checked, onChange, disabled, label, labelClassName }: ToggleSwitchProps) {
  return (
    <label className={`inline-flex items-center gap-2 ${disabled ? 'opacity-60 cursor-not-allowed' : 'cursor-pointer'}`}>
      {label && <span className={`text-xs font-bold uppercase ${labelClassName ?? 'text-slate-600 dark:text-slate-300'}`}>{label}</span>}
      <span
        role="switch"
        aria-checked={checked}
        aria-disabled={disabled}
        onClick={() => !disabled && onChange()}
        className={`relative inline-flex flex-shrink-0 h-6 w-11 items-center rounded-full border-2 border-transparent transition-colors duration-200 ${
          checked ? 'bg-green-500' : 'bg-gray-300 dark:bg-gray-600'
        } ${disabled ? '' : 'hover:opacity-90'}`}
      >
        <span
          className="inline-block h-5 w-5 rounded-full bg-white shadow-md transition-transform duration-200"
          style={{ transform: checked ? 'translateX(20px)' : 'translateX(0px)' }}
        />
      </span>
    </label>
  );
}

export default ToggleSwitch;
