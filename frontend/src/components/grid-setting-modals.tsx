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
        upper_limit: 0,
        lower_limit: 0,
        max_position_size: 0,
        order_size: 0,
    });
    const { 
        isLoading, 
        ask_diff, 
        bid_diff, 
        gridBotStatus, 
        time_update_entry: time_update, 
        entrySymbol  
    } = useGetSummaryStreamData(url)

    const setupGridMutation = useMutation({
            mutationFn: (url: string) => setupGridParameters(url, formData),
            onSuccess: () => {
              alert('Grid parameters updated successfully!');
              setFormData(formData)
              
              // revert the button state after 2 seconds
              setTimeout(() => {
                setupGridMutation.reset();
              }, 2 * SECOND);
            },
            onError: (error: any) => {
              alert('Failed to update grid parameters. Please try again.');  
              console.error('Error setting grid parameters:', error);
        
              setTimeout(() => {
                setupGridMutation.reset();
              }, 4 * SECOND);
            },
          });

    const handleChange = (e:any) => {
        const { name, value } = e.target;
        const parsed = parseFloat(value);
        setFormData((prevData) => ({
            ...prevData,
            [name]: value === "" || isNaN(parsed) ? value : parsed
        }));
    };

    const handleSubmit = (e: any) => {
        // CRITICAL FIX: Prevent the page from reloading
        if (e) e.preventDefault();
        
        setupGridMutation.mutate(url);
    };

    useEffect(() => {
        hasInitialized.current = false;
    }, [url]);

    useEffect(() => {
        if (data && !hasInitialized.current) {
            setFormData({
                upper_limit: data.upper_limit,
                lower_limit: data.lower_limit,
                max_position_size: data.max_position_size,
                order_size: data.order_size,
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
                        <PauseGridBotBtn url={url} gridBotStatus={gridBotStatus} />
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
                                <div className="mt-2 inline-block px-4 py-2 bg-slate-100 rounded-3xl">
                                    <div className="flex flex-col items-center justify-center space-y-0.5">
                                        <p className="text-[11px] text-slate-600 font-bold font-mono uppercase whitespace-nowrap">
                                            Symbol: <span className="text-[#FFC640]">{entrySymbol}</span> 
                                        </p>

                                        <p className="text-[11px] text-slate-600 font-bold font-mono uppercase whitespace-nowrap">
                                            Ask Diff: <span className="text-blue-600">{ask_diff || '0.00'}</span>
                                            <span className="mx-2 text-slate-300">|</span>
                                            Bid Diff: <span className="text-blue-600">{bid_diff || '0.00'}</span>
                                        </p>
                                        
                                        <p className="text-[11px] text-slate-600 font-bold font-mono uppercase whitespace-nowrap">
                                            Status: <span className={gridBotStatus?.toLowerCase() === 'pause' ? 'text-red-500' : 'text-green-600'}>
                                                {gridBotStatus || 'UNKNOWN'}
                                            </span>
                                            <span className="mx-2 text-slate-300">|</span>
                                            {time_update || '0000-00-00 00:00:00'}
                                        </p>
                                    </div>
                                </div>
                            )}
                        </div>

                        {data === null && (
                            <p className="text-xs text-amber-600 font-semibold text-center mb-3 bg-amber-50 border border-amber-200 rounded-lg py-2">
                                No grid setting found
                            </p>
                        )}

                        <form onSubmit={handleSubmit} className="space-y-1">
                            <div className="grid grid-cols-2 gap-4">
                                <FloatingLabelInput label="Upper Limit ($)" name="upper_limit" value={formData.upper_limit} onChange={handleChange} />
                                <FloatingLabelInput label="Lower Limit ($)" name="lower_limit" value={formData.lower_limit} onChange={handleChange} />
                            </div>

                            <div className="grid grid-cols-2 gap-4">
                                <FloatingLabelInput label="Max Pos Size" name="max_position_size" value={formData.max_position_size} onChange={handleChange} />
                                <FloatingLabelInput label="Order Size" name="order_size" value={formData.order_size} onChange={handleChange} />
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
                    </div>
                </div>
            </div>
        </div>
    );
};