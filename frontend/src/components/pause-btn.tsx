/* eslint-disable @typescript-eslint/no-explicit-any */
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { pauseDisplay } from '../query/apis';
import { SECOND } from '../constant/time';
import type { IDokcerAPIBtnProps } from '../interfaces/ button-docker.interface';

function PausePositionBtn({ url }: IDokcerAPIBtnProps) {
  const queryClient = useQueryClient();

  const pauseMutation = useMutation({
    mutationFn: (url: string) => pauseDisplay(url),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['arbitrageSummary'] });
      
      // revert the button state after 1.5 seconds
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
  let btnText = 'Pause position sync toggle';
  let btnClasses = "mb-4 font-semibold py-2 px-4 rounded transition duration-200 border ";
  let message = "";
  let messageClass = "mt-2 h-5 text-sm font-semibold ";

  if (pauseMutation.isPending) {
    btnText = 'Calling API...';
    btnClasses += "bg-gray-400 text-[#e62739] opacity-75 cursor-not-allowed";
    message = "Sending request to toggle pause...";
  } else if (pauseMutation.isSuccess) {
    btnText = 'Toggle pause success!';
    btnClasses += "bg-green-500 hover:bg-green-600 text-[#e62739]";
    message = "API call successful.";
    messageClass += "text-green-500";
  } else if (pauseMutation.isError) {
    btnText = 'Error! Try Again';
    btnClasses += "bg-red-500 hover:bg-red-600 text-[#e62739]";
    message = (pauseMutation.error as any)?.message || "API call failed.";
    messageClass += "text-red-500";
  } else {
    // Initial / Idle state (Matches HTML blue outline style)
    btnClasses += "hover:bg-blue-500 text-blue-700 border-blue-500 hover:border-transparent hover:text-[#e62739]";
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

export default PausePositionBtn;