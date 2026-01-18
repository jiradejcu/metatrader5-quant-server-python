/* eslint-disable @typescript-eslint/no-explicit-any */
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { stopBotService } from "../query/apis";
import { SECOND } from "../constant/time";

function StopBotContainerBtn () {
    const queryClient = useQueryClient()

    const stopBotMutation = useMutation({
        mutationFn: stopBotService,
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['botServerStatus']})

            setTimeout(() => {
                stopBotMutation.reset()
            }, 2 * SECOND)
        },
        onError: (error: any) => {
            console.error('Error stoping bot server: ', error);
            
            setTimeout(() => {
                stopBotMutation.reset()
            }, 4 * SECOND);
        }
    })

    const handleStopBotServer = () => {
        stopBotMutation.mutate()
    } 

    let btnText = 'Stop Bot Server'
    let btnClasses = 'mb-4 font-semibold py-2 px-4 rounded transition duration-200 border'
    let message = "";
    let messageClass = "mt-2 h-5 text-sm font-semibold ";

    if (stopBotMutation.isPending) {
        btnText = 'Calling API...';
        btnClasses += "bg-gray-400 text-[#e62739] opacity-75 cursor-not-allowed";
        message = "Sending request to stop container...";
    } else if (stopBotMutation.isSuccess) {
        btnText = 'Stop bot server success!';
        btnClasses += "bg-green-500 hover:bg-green-600 text-[#e62739]";
        message = "API call successful.";
        messageClass += "text-green-500";
    } else if (stopBotMutation.isError) {
        btnText = 'Error! Try Again';
        btnClasses += "bg-red-500 hover:bg-red-600 text-[#e62739]";
        message = (stopBotMutation.error as any)?.message || "API call failed.";
        messageClass += "text-red-500";
    } else {
        btnClasses += "hover:bg-blue-500 text-blue-700 border-blue-500 hover:border-transparent hover:text-[#e62739]";
    }

    return (
    <>
      <button 
        onClick={handleStopBotServer} 
        disabled={stopBotMutation.isPending}
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

export default StopBotContainerBtn