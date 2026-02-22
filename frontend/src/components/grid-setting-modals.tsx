import { useEffect, useRef, useState } from 'react';
import type { IDokcerAPIBtnProps } from '../interfaces/ button-docker.interface';
import PauseGridBotBtn from './pause-grid-btn';
import { FloatingLabelInput } from './float-input';
import { SECOND } from '../constant/time';
import { useMutation } from '@tanstack/react-query';
import { useGetSummaryStreamData } from '../hooks/summary';
import { setupGridParameters } from '../query/apis';
import { useGetGridSettingsStreamData } from '../hooks/grid-settings';

export const GridSettingModal = (
    { url }: IDokcerAPIBtnProps
) => {
    const [isOpen, setIsOpen] = useState(false);
    const { data } = useGetGridSettingsStreamData(url)
    const hasInitialized = useRef(false);
    const [formData, setFormData] = useState({
        upper_diff: 0.3,
        lower_diff: -0.3,
        max_position_size: 0.03,
        order_size: 0.02,
        close_long: 0.1,
        close_short: -0.1
    });
    const { price_diff_percent, gridBotStatus, time_update_binance: time_update  } = useGetSummaryStreamData(url)

    const setupGridMutation = useMutation({
            mutationFn: (url: string) => setupGridParameters(url, formData),
            onSuccess: (res: any) => {
              console.log('Grid parameters updated successfully:', res);
              setFormData(formData)
              
              // revert the button state after 2 seconds
              setTimeout(() => {
                setupGridMutation.reset();
              }, 2 * SECOND);
            },
            onError: (error: any) => {
              console.error('Error setting grid parameters:', error);
        
              setTimeout(() => {
                setupGridMutation.reset();
              }, 4 * SECOND);
            },
          });

    const [isLoading, setIsLoading] = useState(false);

    const handleChange = (e:any) => {
        const { name, value } = e.target;
        setFormData((prevData) => ({
            ...prevData,
            [name]: value === "" ? 0 : parseFloat(value) // Convert to number or set to empty string
        }));
    };

    const handleSubmit = () => {
        setIsLoading(true);
        setupGridMutation.mutate(url)

        // Simulate API call
        setTimeout(() => {
            console.log("Form submitted with data:", formData);
            setIsLoading(false);
        }, 2 * SECOND);
    }

    useEffect(() => {
        if (data && !hasInitialized.current) {
            setFormData({
                upper_diff: data.upper_diff,
                lower_diff: data.lower_diff,
                max_position_size: data.max_position_size,
                order_size: data.order_size,
                close_long: data.close_long,
                close_short: data.close_short
            });
            hasInitialized.current = true;
        }
    }, [data])
    

    return (
        <div className='mb-4'>
            {/* Main Trigger Button */}
            <button
                onClick={() => setIsOpen(true)}
                className="px-6 py-2 bg-blue-600 text-blue rounded-md font-bold hover:bg-blue-700 transition-all shadow-lg active:scale-95"
                type="button"
            >
                Configure Grid Settings
            </button>

            {/* Modal Overlay / Backdrop */}
            <div
                onClick={() => setIsOpen(false)}
                className={`fixed inset-0 z-[999] grid h-screen w-screen place-items-center bg-slate-900/70 backdrop-blur-sm transition-opacity duration-300 ${
                isOpen ? "opacity-100 pointer-events-auto" : "opacity-0 pointer-events-none"
                }`}
            >
                {/* Modal Content Container */}
                <div
                onClick={(e) => e.stopPropagation()}
                className={`flex flex-col items-center max-w-md w-full px-4 transition-transform duration-300 ${
                    isOpen ? "scale-100" : "scale-95"
                }`}
                >
                    {/* Action Header */}
                    <div className="w-full flex justify-between items-center mb-4">
                        <PauseGridBotBtn url={url} />
                        <button 
                        onClick={() => setIsOpen(false)}
                        className="bg-white/20 hover:bg-white/40 text-blue px-3 py-1 rounded-md text-sm transition-colors border border-white/30"
                        >
                        ✕ Close
                        </button>
                    </div>

                    {/* Main Form Card */}
                    <div className="bg-white p-8 rounded-2xl shadow-2xl w-full border border-slate-200">
                        <div className="mb-6 text-center">
                            <h2 className="text-2xl font-black text-slate-800 uppercase tracking-tight">Grid Bot Settings</h2>
                            {isLoading ? (
                                <p className="text-xs text-blue-600 animate-pulse mt-1 font-bold">Syncing data...</p>
                            ) : (
                                <div className="mt-2 inline-block px-3 py-1 bg-slate-100 rounded-full">
                                <p className="text-[11px] text-slate-600 font-bold font-mono uppercase">
                                    Diff: <span className="text-blue-600">{price_diff_percent || 0}%</span> | Status {gridBotStatus} | {time_update}
                                </p>
                                </div>
                            )}
                        </div>

                        <form onSubmit={handleSubmit} className="space-y-1">
                            <div className="grid grid-cols-2 gap-4">
                                <FloatingLabelInput label="Upper Diff (%)" name="upper_diff" value={formData.upper_diff} onChange={handleChange} />
                                <FloatingLabelInput label="Lower Diff (%)" name="lower_diff" value={formData.lower_diff} onChange={handleChange} />
                            </div>

                            <div className="grid grid-cols-2 gap-4">
                                <FloatingLabelInput label="Max Pos Size" name="max_position_size" value={formData.max_position_size} onChange={handleChange} step="0.001" />
                                <FloatingLabelInput label="Order Size" name="order_size" value={formData.order_size} onChange={handleChange} step="0.001" />
                            </div>

                            <div className="grid grid-cols-2 gap-4">
                                <FloatingLabelInput label="TP Long (%)" name="close_long" value={formData.close_long} onChange={handleChange} />
                                <FloatingLabelInput label="TP Short (%)" name="close_short" value={formData.close_short} onChange={handleChange} />
                            </div>

                            <button
                                type="submit"
                                disabled={setupGridMutation.isPending}
                                className={`w-full mt-6 py-3.5 px-4 rounded-xl font-black text-sm uppercase tracking-widest text-blue shadow-lg transition-all active:scale-[0.97]
                                ${setupGridMutation.isPending 
                                    ? "bg-slate-300 cursor-not-allowed" 
                                    : "bg-blue-600 hover:bg-blue-700 shadow-blue-200"
                                }`}
                            >
                                {setupGridMutation.isPending ? "Saving..." : "Update Parameters"}
                            </button>
                        </form>

                        <div className="mt-6 flex justify-center border-t border-slate-100 pt-4">
                            <button 
                                type="button"
                                onClick={() => setIsOpen(false)}
                                className="text-xs text-slate-400 hover:text-red-500 transition-colors font-bold uppercase tracking-wider"
                            >
                                Cancel & Return
                            </button>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    );
};