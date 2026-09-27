interface LedIndicatorProps {
  active: boolean;
  // Amber override for an active-but-degraded state (e.g. grid bot recovery mode).
  warning?: boolean;
  label?: string;
  inactiveLabelClassName?: string;
}

export function LedIndicator({ active, warning, label, inactiveLabelClassName }: LedIndicatorProps) {
  const ledClassName = warning
    ? 'bg-amber-500 shadow-[0_0_6px_2px_rgba(245,158,11,0.6)]'
    : active
      ? 'bg-green-500 shadow-[0_0_6px_2px_rgba(34,197,94,0.6)]'
      : 'bg-gray-300 dark:bg-gray-600';
  const labelClassName = warning
    ? 'text-amber-600'
    : active
      ? 'text-green-600'
      : inactiveLabelClassName ?? 'text-gray-400 dark:text-gray-500';

  return (
    <span className="inline-flex items-center gap-1.5">
      <span className={`inline-block w-2.5 h-2.5 rounded-full transition-colors ${ledClassName}`} />
      {label && (
        <span className={`text-xs font-bold uppercase ${labelClassName}`}>
          {label}
        </span>
      )}
    </span>
  );
}

export default LedIndicator;
