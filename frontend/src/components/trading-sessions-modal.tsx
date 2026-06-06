import { useState, useEffect } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { getTradingSessions, setTradingSessions, ApiError } from '../query/apis';
import type { TradingSessions, TimeRange } from '../query/apis';
import type { IDokcerAPIBtnProps } from '../interfaces/ button-docker.interface';
import { SECOND } from '../constant/time';

const DAYS = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];

const DEFAULT_SESSIONS: TradingSessions = {
    Sunday: [{ start: '22:01', end: '24:00' }],
    Monday: [{ start: '00:00', end: '20:58' }, { start: '22:00', end: '24:00' }],
    Tuesday: [{ start: '00:00', end: '20:58' }, { start: '22:00', end: '24:00' }],
    Wednesday: [{ start: '00:00', end: '20:58' }, { start: '22:00', end: '24:00' }],
    Thursday: [{ start: '00:00', end: '20:58' }, { start: '22:00', end: '24:00' }],
    Friday: [{ start: '00:00', end: '20:58' }],
    Saturday: [],
};

function TimeRangeInput({
    range,
    onChange,
    onRemove,
}: {
    range: TimeRange;
    onChange: (r: TimeRange) => void;
    onRemove: () => void;
}) {
    return (
        <div className="flex items-center gap-1">
            <input
                type="text"
                value={range.start}
                onChange={(e) => onChange({ ...range, start: e.target.value })}
                placeholder="HH:MM"
                className="w-16 text-xs border border-slate-300 rounded px-1 py-0.5 font-mono text-center focus:outline-none focus:ring-1 focus:ring-blue-400"
            />
            <span className="text-xs text-slate-400">–</span>
            <input
                type="text"
                value={range.end}
                onChange={(e) => onChange({ ...range, end: e.target.value })}
                placeholder="HH:MM"
                className="w-16 text-xs border border-slate-300 rounded px-1 py-0.5 font-mono text-center focus:outline-none focus:ring-1 focus:ring-blue-400"
            />
            <button
                type="button"
                onClick={onRemove}
                className="text-red-400 hover:text-red-600 text-xs px-1"
            >
                ✕
            </button>
        </div>
    );
}

export const TradingSessionsModal = ({ url }: IDokcerAPIBtnProps) => {
    const [isOpen, setIsOpen] = useState(false);
    const [sessions, setSessions] = useState<TradingSessions>(DEFAULT_SESSIONS);
    const [notification, setNotification] = useState<{ type: 'success' | 'error'; messages: string[] } | null>(null);
    const queryClient = useQueryClient();

    const { data: fetched, isError: isFetchError } = useQuery<TradingSessions>({
        queryKey: ['trading-sessions', url],
        queryFn: () => getTradingSessions(url),
        staleTime: 30 * SECOND,
        retry: false,
    });

    const isAllEmpty = fetched !== undefined && DAYS.every((d) => (fetched[d] ?? []).length === 0);
    const sessionStatus: string | null = isFetchError
        ? 'Unknown'
        : isAllEmpty
        ? 'Grid bot always active'
        : null;

    useEffect(() => {
        setSessions(DEFAULT_SESSIONS);
        setNotification(null);
    }, [url]);

    useEffect(() => {
        if (isOpen && fetched != null) setSessions(fetched);
    }, [isOpen, fetched]);

    const saveMutation = useMutation({
        mutationFn: () => setTradingSessions(url, sessions),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['trading-sessions', url] });
            setNotification({ type: 'success', messages: ['Trading sessions saved!'] });
            setTimeout(() => {
                saveMutation.reset();
                setNotification(null);
            }, 2 * SECOND);
        },
        onError: (error: unknown) => {
            const messages = error instanceof ApiError
                ? error.messages
                : ['Failed to save sessions. Please try again.'];
            setNotification({ type: 'error', messages });
            setTimeout(() => {
                saveMutation.reset();
                setNotification(null);
            }, 4 * SECOND);
        },
    });

    const updateRange = (day: string, idx: number, updated: TimeRange) => {
        setSessions((prev) => {
            const ranges = [...(prev[day] ?? [])];
            ranges[idx] = updated;
            return { ...prev, [day]: ranges };
        });
    };

    const removeRange = (day: string, idx: number) => {
        setSessions((prev) => {
            const ranges = (prev[day] ?? []).filter((_, i) => i !== idx);
            return { ...prev, [day]: ranges };
        });
    };

    const addRange = (day: string) => {
        setSessions((prev) => ({
            ...prev,
            [day]: [...(prev[day] ?? []), { start: '00:00', end: '24:00' }],
        }));
    };

    return (
        <div className="mb-4">
            <button
                onClick={() => setIsOpen(true)}
                className="px-6 py-2 bg-indigo-600 text-white rounded-md font-bold hover:bg-indigo-700 transition-all shadow-lg active:scale-95"
                type="button"
            >
                Trading Sessions
            </button>
            {sessionStatus && (
                <p className={`text-xs mt-1 font-medium ${isFetchError ? 'text-red-500' : 'text-green-600'}`}>
                    {sessionStatus}
                </p>
            )}

            <div
                onClick={() => setIsOpen(false)}
                className={`fixed inset-0 z-[999] grid h-screen w-screen place-items-center bg-slate-900/70 backdrop-blur-sm transition-opacity duration-300 ${
                    isOpen ? 'opacity-100 pointer-events-auto' : 'opacity-0 pointer-events-none'
                }`}
            >
                <div
                    onClick={(e) => e.stopPropagation()}
                    className={`flex flex-col items-center max-w-lg w-full px-4 transition-transform duration-300 ${
                        isOpen ? 'scale-100' : 'scale-95'
                    }`}
                >
                    <div className="w-full flex justify-end mb-4">
                        <button
                            onClick={() => setIsOpen(false)}
                            className="bg-white/20 hover:bg-white/40 text-white px-3 py-1 rounded-md text-sm transition-colors border border-white/30"
                        >
                            ✕ Close
                        </button>
                    </div>

                    <div className="bg-white p-8 rounded-2xl shadow-2xl w-full border border-slate-200 max-h-[80vh] overflow-y-auto">
                        <div className="mb-5 text-center">
                            <h2 className="text-2xl font-black text-slate-800 uppercase tracking-tight">Trading Sessions</h2>
                            <p className="text-xs text-slate-500 mt-1">Times are UTC. "24:00" = end of day.</p>
                        </div>

                        {isFetchError ? (
                            <div className="py-6 text-center text-sm font-semibold text-red-500">
                                {sessionStatus}
                            </div>
                        ) : (
                            <div className="space-y-3">
                                {DAYS.map((day) => (
                                    <div key={day} className="border border-slate-100 rounded-lg px-3 py-2 bg-slate-50">
                                        <div className="flex items-center justify-between mb-1.5">
                                            <span className="text-sm font-bold text-slate-700 w-24">{day}</span>
                                            <button
                                                type="button"
                                                onClick={() => addRange(day)}
                                                className="text-xs text-blue-600 hover:text-blue-800 font-semibold"
                                            >
                                                + Add
                                            </button>
                                        </div>
                                        {(sessions[day] ?? []).length === 0 ? (
                                            <span className="text-xs text-slate-400 italic">Closed</span>
                                        ) : (
                                            <div className="flex flex-col gap-1">
                                                {(sessions[day] ?? []).map((range, idx) => (
                                                    <TimeRangeInput
                                                        key={idx}
                                                        range={range}
                                                        onChange={(r) => updateRange(day, idx, r)}
                                                        onRemove={() => removeRange(day, idx)}
                                                    />
                                                ))}
                                            </div>
                                        )}
                                    </div>
                                ))}
                            </div>
                        )}

                        {notification && (
                            <div className={`mt-4 px-4 py-3 rounded-lg border text-sm font-semibold ${
                                notification.type === 'success'
                                    ? 'bg-green-50 border-green-300 text-green-800'
                                    : 'bg-red-50 border-red-300 text-red-800'
                            }`}>
                                {notification.messages.map((msg, i) => <p key={i}>{msg}</p>)}
                            </div>
                        )}

                        <button
                            type="button"
                            onClick={() => saveMutation.mutate()}
                            disabled={saveMutation.isPending}
                            className={`w-full mt-6 py-3.5 px-4 rounded-xl font-black text-sm uppercase tracking-widest text-white shadow-lg transition-all active:scale-[0.97] ${
                                saveMutation.isPending
                                    ? 'bg-slate-300 cursor-not-allowed'
                                    : 'bg-indigo-600 hover:bg-indigo-700 shadow-indigo-200'
                            }`}
                        >
                            {saveMutation.isPending ? 'Saving...' : 'Save Sessions'}
                        </button>
                    </div>
                </div>
            </div>
        </div>
    );
};
