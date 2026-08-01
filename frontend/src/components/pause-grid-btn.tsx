
import { useMutation, useQueryClient } from '@tanstack/react-query';
import type { IDokcerAPIBtnProps } from '../interfaces/ button-docker.interface';
import { toggleGridBot } from '../query/apis';
import { SECOND } from '../constant/time';
import { ToggleSwitch } from './toggle-switch';

interface PauseGridBotBtnProps extends IDokcerAPIBtnProps {
  labelClassName?: string;
  label?: string;
}

function PauseGridBotBtn ({ url, gridBotEnabled, labelClassName, label }: PauseGridBotBtnProps) {
    const queryClient = useQueryClient();
    const pauseMutation = useMutation({
        mutationFn: (url: string) => toggleGridBot(url),
        onSuccess: () => {
          queryClient.invalidateQueries({ queryKey: ['arbitrage', 'summary', url] });

          setTimeout(() => {
            pauseMutation.reset();
          }, 2 * SECOND);
        },
        onError: (error: any) => {
          console.error('Error pausing display:', error);

          setTimeout(() => {
            pauseMutation.reset();
          }, 4 * SECOND);
        },
      });

      const handleToggle = () => {
        pauseMutation.mutate(url);
      };

      const isEnabled = gridBotEnabled?.toLowerCase() === 'active';

      let message = "";
      let messageClass = "absolute top-full left-0 mt-1 text-xs font-semibold whitespace-nowrap ";

      if (pauseMutation.isPending) {
        message = "Sending request...";
        messageClass += "text-gray-500";
      } else if (pauseMutation.isSuccess) {
        message = "Updated!";
        messageClass += "text-green-500";
      } else if (pauseMutation.isError) {
        message = (pauseMutation.error as any)?.message || "API call failed.";
        messageClass += "text-red-500";
      }

      return (
        <div className="relative inline-flex items-center">
          <ToggleSwitch
            label={label ?? "Grid Bot"}
            labelClassName={labelClassName}
            checked={isEnabled}
            onChange={handleToggle}
            disabled={pauseMutation.isPending}
          />
          {message && <p className={messageClass}>{message}</p>}
        </div>
      );
}

export default PauseGridBotBtn;
