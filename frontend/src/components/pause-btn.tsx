/* eslint-disable @typescript-eslint/no-explicit-any */
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { pauseDisplay } from '../query/apis';
import { SECOND } from '../constant/time';
import type { IDokcerAPIBtnProps } from '../interfaces/ button-docker.interface';
import { useGetSummaryStreamData } from '../hooks/summary';

function PausePositionBtn({ url }: IDokcerAPIBtnProps) {
  const queryClient = useQueryClient();
  const { pausePositionSync } = useGetSummaryStreamData(url);
  const isPaused = pausePositionSync !== 'Active';

  const pauseMutation = useMutation({
    mutationFn: (url: string) => pauseDisplay(url),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['arbitrageSummary'] });
      setTimeout(() => pauseMutation.reset(), 2 * SECOND);
    },
    onError: (error: any) => {
      console.error('Error toggling position sync:', error);
      setTimeout(() => pauseMutation.reset(), 4 * SECOND);
    },
  });

  const label = isPaused ? 'Resume Position Sync' : 'Pause Position Sync';
  let btnClass = 'w-full mt-3 py-2 px-4 rounded-lg font-semibold text-sm transition-all duration-200 ';
  let statusText = '';
  let statusClass = 'mt-1 h-4 text-xs font-medium ';

  if (pauseMutation.isPending) {
    btnClass += 'opacity-50 cursor-not-allowed ';
    btnClass += isPaused
      ? 'bg-green-500 dark:bg-green-600 text-white'
      : 'bg-amber-400 dark:bg-amber-500 text-gray-900';
  } else if (pauseMutation.isSuccess) {
    btnClass += 'bg-green-500 hover:bg-green-600 text-white';
    statusText = 'Success.';
    statusClass += 'text-green-500';
  } else if (pauseMutation.isError) {
    btnClass += 'bg-red-500 hover:bg-red-600 text-white';
    statusText = (pauseMutation.error as any)?.message ?? 'API call failed.';
    statusClass += 'text-red-500';
  } else if (isPaused) {
    btnClass += 'bg-green-500 hover:bg-green-600 dark:bg-green-600 dark:hover:bg-green-700 text-white';
  } else {
    btnClass += 'bg-amber-400 hover:bg-amber-500 dark:bg-amber-500 dark:hover:bg-amber-600 text-gray-900';
  }

  return (
    <>
      <button
        onClick={() => pauseMutation.mutate(url)}
        disabled={pauseMutation.isPending}
        className={btnClass}
      >
        {label}
      </button>
      <p className={statusClass}>{statusText}</p>
    </>
  );
}

export default PausePositionBtn;
