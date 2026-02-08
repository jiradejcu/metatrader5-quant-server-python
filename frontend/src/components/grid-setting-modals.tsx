import { useState } from 'react';
import type { IDokcerAPIBtnProps } from '../interfaces/ button-docker.interface';
import { useGetGridSettingsStreamData } from '../hooks/grid-settings';

export const GridSettingModal = (
    { url }: IDokcerAPIBtnProps
) => {
    const [isOpen, setIsOpen] = useState(false);
    const { data, isLoading } = useGetGridSettingsStreamData(url)
    
    if (isLoading) {
        return <div>Fetching grid_parameter data ...</div>
    }
    

    return (
        <>
            <button 
                onClick={() => setIsOpen(true)}
                className="hover:bg-blue-500 text-blue-700 border-blue-500 hover:border-transparent hover:text-[#e62739] mb-8" 
                type="button">
                Open Modal
            </button>

            {/* Backdrop */}
            <div
                onClick={() => setIsOpen(false)}
                className={`fixed inset-0 z-[999] grid h-screen w-screen place-items-center bg-black bg-opacity-60 backdrop-blur-sm transition-opacity duration-300 ${
                    isOpen ? "opacity-100 pointer-events-auto" : "opacity-0 pointer-events-none"
                }`}
            >
                {/* Modal Content */}
                <div
                    onClick={(e) => e.stopPropagation()} // Prevent closing when clicking inside the modal
                    className="relative m-4 p-4 w-2/5 rounded-lg bg-white shadow-sm"
                >
                    <div className="text-xl font-medium text-slate-800">Its a simple Modal</div>
                    <div className="border-t border-slate-200 py-4 text-slate-600">
                        The key to more success is to have a lot of pillows
                        lower_diff: {data?.lower_diff}
                        upper_diff: {data?.upper_diff}
                        mark_price: {data?.mark_price}
                        time: {data?.time}
                    </div>
                    <div className="flex justify-end pt-4">
                        <button onClick={() => setIsOpen(false)} className="text-slate-600 px-4 mr-4">Cancel</button>
                        <button onClick={() => setIsOpen(false)} className="hover:bg-blue-500 text-blue-700 border-blue-500 hover:border-transparent hover:text-[#e62739]">Confirm</button>
                    </div>
                </div>
            </div>
        </>
    );
};