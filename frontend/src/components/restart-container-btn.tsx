/* eslint-disable @typescript-eslint/no-explicit-any */
import { useMutation } from '@tanstack/react-query';
import { restartBotService } from '../query/apis';
import { SECOND } from '../constant/time';
import type { IDokcerAPIBtnProps } from '../interfaces/ button-docker.interface';

function RestartBotContainerBtn({ url }: IDokcerAPIBtnProps) {
  const restartMutation = useMutation({
    mutationFn: (url: string) => restartBotService(url),
    onSuccess: () => {
      setTimeout(() => restartMutation.reset(), 2 * SECOND);
    },
    onError: (error: any) => {
      console.error('Error restarting bot server:', error);
      setTimeout(() => restartMutation.reset(), 4 * SECOND);
    },
  });

  const label = 'Restart Bot Server';
  let btnClass = 'w-full mt-1 mb-3 py-2 px-4 rounded-lg font-semibold text-sm transition-all duration-200 ';
  let statusText = '';
  let statusClass = 'mt-1 h-4 text-xs font-medium ';

  if (restartMutation.isPending) {
    btnClass += 'bg-orange-500 dark:bg-orange-600 text-white opacity-50 cursor-not-allowed';
  } else if (restartMutation.isSuccess) {
    btnClass += 'bg-green-500 hover:bg-green-600 text-white';
    statusText = 'Success.';
    statusClass += 'text-green-500';
  } else if (restartMutation.isError) {
    btnClass += 'bg-red-500 hover:bg-red-600 text-white';
    statusText = (restartMutation.error as any)?.message ?? 'API call failed.';
    statusClass += 'text-red-500';
  } else {
    btnClass += 'bg-orange-500 hover:bg-orange-600 dark:bg-orange-600 dark:hover:bg-orange-700 text-white';
  }

  return (
    <>
      <button
        onClick={() => restartMutation.mutate(url)}
        disabled={restartMutation.isPending}
        className={btnClass}
      >
        {label}
      </button>
      <p className={statusClass}>{statusText}</p>
    </>
  );
}

export default RestartBotContainerBtn;
