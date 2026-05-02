
import { useMutation, useQueryClient } from '@tanstack/react-query';
import type { IDokcerAPIBtnProps } from '../interfaces/ button-docker.interface';
import { pauseGridBot } from '../query/apis';
import { SECOND } from '../constant/time';

function PauseGridBotBtn ({ url }: IDokcerAPIBtnProps) {
    const queryClient = useQueryClient();
    const pauseMutation = useMutation({
        mutationFn: (url: string) => pauseGridBot(url),
        onSuccess: () => {
          queryClient.invalidateQueries({ queryKey: ['arbitrage', 'summary', url] });
          
          // revert the button state after 2 seconds
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
    
      const handlePause = () => {
        pauseMutation.mutate(url); 
      };
    
      // Derive all UI states directly from the mutation object
      let btnText = 'Pause Grid Bot';
      let btnClasses = "mb-4 font-semibold py-2 px-4 rounded transition duration-200 border ";
      let message = "";
      let messageClass = "mt-2 h-5 text-sm font-semibold ";
    
      if (pauseMutation.isPending) {
        btnText = 'Calling API...';
        btnClasses += "bg-gray-400 text-white opacity-75 cursor-not-allowed";
        message = "Sending request to toggle pause...";
      } else if (pauseMutation.isSuccess) {
        btnText = 'Toggle pause success!';
        btnClasses += "bg-green-500 hover:bg-green-600 text-white";
        message = "API call successful.";
        messageClass += "text-green-500";
      } else if (pauseMutation.isError) {
        btnText = 'Error! Try Again';
        btnClasses += "bg-red-500 hover:bg-red-600 text-white";
        message = (pauseMutation.error as any)?.message || "API call failed.";
        messageClass += "text-red-500";
      } else {
        // Initial / Idle state
        btnClasses += "bg-amber-400 hover:bg-amber-500 dark:bg-amber-500 dark:hover:bg-amber-600 text-gray-900 border-amber-500";
      }
    
      return (
        <>
          <button 
            onClick={handlePause} 
            disabled={pauseMutation.isPending}
            className={btnClasses}
          >
            {btnText}
          </button>
          
          <p className={messageClass}>
            {message}
          </p>
        </>
      );
}

export default PauseGridBotBtn;