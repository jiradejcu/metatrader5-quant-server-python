
import { useMutation, useQueryClient } from '@tanstack/react-query';
import type { IDokcerAPIBtnProps } from '../interfaces/ button-docker.interface';
import { toggleGridBot } from '../query/apis';
import { SECOND } from '../constant/time';
import { ToggleSwitch } from './toggle-switch';

function PauseGridBotBtn ({ url, gridBotEnabled }: IDokcerAPIBtnProps) {
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
      let messageClass = "mt-1 h-4 text-xs font-semibold ";

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
        <div className="mb-2">
          <ToggleSwitch
            label="Grid Bot"
            checked={isEnabled}
            onChange={handleToggle}
            disabled={pauseMutation.isPending}
          />
          <p className={messageClass}>
            {message}
          </p>
        </div>
      );
}

export default PauseGridBotBtn;
