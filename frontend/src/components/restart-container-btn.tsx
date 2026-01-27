/* eslint-disable @typescript-eslint/no-explicit-any */
import { useMutation } from "@tanstack/react-query";
import { restartBotService } from "../query/apis";
import { SECOND } from "../constant/time";
import type { IDokcerAPIBtnProps } from "../interfaces/ button-docker.interface";

function RestartBotContainerBtn ({ url }: IDokcerAPIBtnProps) {
    const restartBotMutation = useMutation({
        mutationFn: (url: string) => restartBotService(url),
        onSuccess: () => {
            setTimeout(() => {
                restartBotMutation.reset()
            }, 2 * SECOND)
        },
        onError: (error: any) => {
            console.error('Error stoping bot server: ', error);
            
            setTimeout(() => {
                restartBotMutation.reset()
            }, 4 * SECOND);
        }
    })

    const handleRestartBotServer = () => {
        restartBotMutation.mutate(url)
    } 

    let btnText = 'Restart Bot Server'
    let btnClasses = 'mb-4 font-semibold py-2 px-4 rounded transition duration-200 border'
    let message = "";
    let messageClass = "mt-2 h-5 text-sm font-semibold ";

    if (restartBotMutation.isPending) {
        btnText = 'Calling API...';
        btnClasses += "bg-gray-400 text-[#e62739] opacity-75 cursor-not-allowed";
        message = "Sending request to restart container...";
    } else if (restartBotMutation.isSuccess) {
        btnText = 'Restart bot server success!';
        btnClasses += "bg-green-500 hover:bg-green-600 text-[#e62739]";
        message = "API call successful.";
        messageClass += "text-green-500";
    } else if (restartBotMutation.isError) {
        btnText = 'Error! Try Again';
        btnClasses += "bg-red-500 hover:bg-red-600 text-[#e62739]";
        message = (restartBotMutation.error as any)?.message || "API call failed.";
        messageClass += "text-red-500";
    } else {
        btnClasses += "hover:bg-blue-500 text-blue-700 border-blue-500 hover:border-transparent hover:text-[#e62739]";
    }

    return (
    <>
      <button 
        onClick={handleRestartBotServer} 
        disabled={restartBotMutation.isPending}
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

export default RestartBotContainerBtn