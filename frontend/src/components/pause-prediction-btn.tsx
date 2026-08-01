import { useMutation, useQueryClient } from '@tanstack/react-query';
import type { IDokcerAPIBtnProps } from '../interfaces/ button-docker.interface';
import { togglePredictionBot } from '../query/apis';
import { SECOND } from '../constant/time';
import { ToggleSwitch } from './toggle-switch';

interface PausePredictionBotBtnProps extends IDokcerAPIBtnProps {
  labelClassName?: string;
  label?: string;
}

function PausePredictionBotBtn ({ url, predictionBotEnabled, labelClassName, label }: PausePredictionBotBtnProps) {
    const queryClient = useQueryClient();
    const pauseMutation = useMutation({
        mutationFn: (url: string) => togglePredictionBot(url),
        onSuccess: () => {
          queryClient.invalidateQueries({ queryKey: ['arbitrage', 'summary', url] });

          setTimeout(() => {
            pauseMutation.reset();
          }, 2 * SECOND);
        },
        onError: (error: any) => {
          console.error('Error toggling prediction bot:', error);

          setTimeout(() => {
            pauseMutation.reset();
          }, 4 * SECOND);
        },
      });

      const handleToggle = () => {
        pauseMutation.mutate(url);
      };

      const isEnabled = predictionBotEnabled?.toLowerCase() === 'active';

      let message = "";
      let messageClass = "mt-1 text-xs font-semibold whitespace-nowrap ";

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
        <div className="inline-flex flex-col items-start">
          <ToggleSwitch
            label={label ?? "Prediction Bot"}
            labelClassName={labelClassName}
            checked={isEnabled}
            onChange={handleToggle}
            disabled={pauseMutation.isPending}
          />
          {message && <p className={messageClass}>{message}</p>}
        </div>
      );
}

export default PausePredictionBotBtn;
