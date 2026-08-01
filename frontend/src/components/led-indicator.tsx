interface LedIndicatorProps {
  active: boolean;
  label?: string;
}

export function LedIndicator({ active, label }: LedIndicatorProps) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span
        className={`inline-block w-2.5 h-2.5 rounded-full transition-colors ${
          active
            ? 'bg-green-500 shadow-[0_0_6px_2px_rgba(34,197,94,0.6)]'
            : 'bg-gray-300 dark:bg-gray-600'
        }`}
      />
      {label && (
        <span className={`text-xs font-bold uppercase ${active ? 'text-green-600' : 'text-gray-400 dark:text-gray-500'}`}>
          {label}
        </span>
      )}
    </span>
  );
}

export default LedIndicator;
