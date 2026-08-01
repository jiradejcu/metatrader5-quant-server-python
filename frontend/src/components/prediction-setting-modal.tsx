import { useEffect, useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { IDokcerAPIBtnProps } from '../interfaces/ button-docker.interface';
import PausePredictionBotBtn from './pause-prediction-btn';
import { LedIndicator } from './led-indicator';
import { FloatingLabelInput } from './float-input';
import { SECOND } from '../constant/time';
import { useGetSummaryStreamData } from '../hooks/summary';
import { getPredictionSettings, setupPredictionParameters, ApiError } from '../query/apis';
import type { PredictionSettings } from '../query/apis';

const DEFAULT_SETTINGS: PredictionSettings = {
    profit_target_usd: 0,
    max_slippage_usd: 0,
    aggressiveness: 'passive',
    reentry_tolerance_usd: 0,
    max_close_size: 0,
    force_aggressive_minutes_before_reopen: 0,
};

export const PredictionSettingModal = (
    { url }: IDokcerAPIBtnProps
) => {
    const [isOpen, setIsOpen] = useState(false);
    const [formData, setFormData] = useState<PredictionSettings>(DEFAULT_SETTINGS);
    const [notification, setNotification] = useState<{ type: 'success' | 'error'; messages: string[] } | null>(null);
    const hasInitialized = useRef(false);
    const queryClient = useQueryClient();

    const { predictionBotEnabled, predictionBotActive } = useGetSummaryStreamData(url);

    const { data: fetched, isError: isFetchError } = useQuery<PredictionSettings>({
        queryKey: ['prediction', 'settings', url],
        queryFn: () => getPredictionSettings(url),
        staleTime: 30 * SECOND,
        retry: false,
    });

    useEffect(() => {
        hasInitialized.current = false;
        setFormData(DEFAULT_SETTINGS);
        setNotification(null);
    }, [url]);

    useEffect(() => {
        if (isOpen && fetched != null && !hasInitialized.current) {
            setFormData(fetched);
            hasInitialized.current = true;
        }
    }, [isOpen, fetched]);

    const setupPredictionMutation = useMutation({
        mutationFn: (url: string) => setupPredictionParameters(url, formData),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['prediction', 'settings', url] });
            setNotification({ type: 'success', messages: ['Prediction parameters updated successfully!'] });

            setTimeout(() => {
                setupPredictionMutation.reset();
                setNotification(null);
            }, 2 * SECOND);
        },
        onError: (error: unknown) => {
            const messages = error instanceof ApiError
                ? error.messages
                : ['Failed to update prediction parameters. Please try again.'];
            setNotification({ type: 'error', messages });
            console.error('Error setting prediction parameters:', error);

            setTimeout(() => {
                setupPredictionMutation.reset();
                setNotification(null);
            }, 4 * SECOND);
        },
    });

    const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
        const { name, value } = e.target;
        const parsed = parseFloat(value);
        setFormData((prevData) => ({
            ...prevData,
            [name]: value === "" || isNaN(parsed) ? value : parsed,
        }));
    };

    const handleAggressivenessChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
        setFormData((prevData) => ({
            ...prevData,
            aggressiveness: e.target.value as PredictionSettings['aggressiveness'],
        }));
    };

    const handleSubmit = (e: React.FormEvent) => {
        e.preventDefault();
        setupPredictionMutation.mutate(url);
    };

    return (
        <div className="flex-1">
            <button
                onClick={() => setIsOpen(true)}
                className="w-full px-6 py-2 bg-purple-600 text-white rounded-md font-bold hover:bg-purple-700 transition-all shadow-lg active:scale-95"
                type="button"
            >
                Configure Prediction Settings
            </button>

            <div
                onClick={() => setIsOpen(false)}
                className={`fixed inset-0 z-[999] grid h-screen w-screen place-items-center bg-slate-900/70 backdrop-blur-sm transition-opacity duration-300 ${
                isOpen ? "opacity-100 pointer-events-auto" : "opacity-0 pointer-events-none"
                }`}
            >
                <div
                onClick={(e) => e.stopPropagation()}
                className={`flex flex-col items-center max-w-md w-full px-4 transition-transform duration-300 ${
                    isOpen ? "scale-100" : "scale-95"
                }`}
                >
                    <div className="w-full flex justify-end items-center mb-4">
                        <button
                        onClick={() => setIsOpen(false)}
                        className="bg-white/20 hover:bg-white/40 text-white px-3 py-1 rounded-md text-sm transition-colors border border-white/30"
                        >
                        ✕ Close
                        </button>
                    </div>

                    <div className="bg-white p-8 rounded-2xl shadow-2xl w-full border border-slate-200 max-h-[80vh] overflow-y-auto">
                        <div className="mb-6 text-center">
                            <h2 className="text-2xl font-black text-slate-800 uppercase tracking-tight">Prediction Bot Settings</h2>
                            <div className="flex items-center justify-between mt-4 mb-1">
                                <PausePredictionBotBtn url={url} predictionBotEnabled={predictionBotEnabled} label="Enable" />
                                <LedIndicator active={predictionBotActive?.toLowerCase() === 'active'} label="Active" />
                            </div>
                        </div>

                        {isFetchError && (
                            <p className="text-xs text-amber-600 font-semibold text-center mb-3 bg-amber-50 border border-amber-200 rounded-lg py-2">
                                Failed to load current settings — showing defaults
                            </p>
                        )}

                        <form onSubmit={handleSubmit} className="space-y-3">
                            <div className="grid grid-cols-2 gap-4">
                                <FloatingLabelInput label="Profit Target ($)" name="profit_target_usd" value={formData.profit_target_usd} onChange={handleChange} step="0.01" />
                                <FloatingLabelInput label="Max Slippage ($)" name="max_slippage_usd" value={formData.max_slippage_usd} onChange={handleChange} step="0.01" />
                            </div>

                            <div className="grid grid-cols-2 gap-4">
                                <FloatingLabelInput label="Reentry Tolerance ($)" name="reentry_tolerance_usd" value={formData.reentry_tolerance_usd} onChange={handleChange} step="0.01" />
                                <FloatingLabelInput label="Max Close Size" name="max_close_size" value={formData.max_close_size} onChange={handleChange} step="0.01" />
                            </div>

                            <div className="grid grid-cols-2 gap-4 items-start">
                                <FloatingLabelInput label="Force Aggressive (min)" name="force_aggressive_minutes_before_reopen" value={formData.force_aggressive_minutes_before_reopen} onChange={handleChange} step="1" />

                                <div className="w-full mb-4">
                                    <label className="block text-xs text-slate-500 font-bold uppercase mb-1">Aggressiveness</label>
                                    <select
                                        name="aggressiveness"
                                        value={formData.aggressiveness}
                                        onChange={handleAggressivenessChange}
                                        className="w-full bg-white text-slate-900 text-sm border-2 border-slate-200 rounded-lg px-3 py-2.5 transition-all focus:outline-none focus:border-purple-600 hover:border-slate-300 shadow-sm"
                                    >
                                        <option value="passive">Passive</option>
                                        <option value="aggressive">Aggressive</option>
                                    </select>
                                </div>
                            </div>

                            {notification && (
                                <div className={`mt-4 px-4 py-3 rounded-lg border text-sm font-semibold ${
                                    notification.type === 'success'
                                        ? 'bg-green-50 border-green-300 text-green-800'
                                        : 'bg-red-50 border-red-300 text-red-800'
                                }`}>
                                    {notification.messages.length === 1 ? (
                                        <p>{notification.messages[0]}</p>
                                    ) : (
                                        <ul className="list-disc list-inside space-y-0.5">
                                            {notification.messages.map((msg, i) => (
                                                <li key={i}>{msg}</li>
                                            ))}
                                        </ul>
                                    )}
                                </div>
                            )}

                            <button
                                type="submit"
                                disabled={setupPredictionMutation.isPending}
                                className={`w-full mt-6 py-3.5 px-4 rounded-xl font-black text-sm uppercase tracking-widest text-white shadow-lg transition-all active:scale-[0.97]
                                ${setupPredictionMutation.isPending
                                    ? "bg-slate-300 cursor-not-allowed"
                                    : "bg-purple-600 hover:bg-purple-700 shadow-purple-200"
                                }`}
                            >
                                {setupPredictionMutation.isPending ? "Saving..." : "Update Parameters"}
                            </button>
                        </form>
                    </div>
                </div>
            </div>
        </div>
    );
};
