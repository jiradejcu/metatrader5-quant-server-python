import { useGetSummaryStreamData } from "../hooks/summary";
import type { ICardSection } from "../interfaces/control-panel.interface";
import type { SpreadHighlightProps } from "../interfaces/spread.interface";

const GlassLine: React.FC = () => (
  <div className="my-6 h-px w-full bg-gradient-to-r from-transparent via-gray-300 to-transparent opacity-60" />
);

const SpreadHighlight: React.FC<SpreadHighlightProps> = ({ spread }) => {
  const isPositive = spread > 0;
  
  return (
    <div className={`mt-6 p-4 rounded-xl border-l-4 shadow-sm transition-colors duration-300 ${
      isPositive 
        ? 'bg-green-50 border-green-500' 
        : 'bg-red-50 border-red-500'
    }`}>
      <div className="flex justify-between items-center">
        <div className="flex flex-col">
          <span className="text-[10px] font-bold text-gray-400 uppercase tracking-widest">Analysis</span>
          <span className="text-sm font-semibold text-gray-700">Market Spread</span>
        </div>
        <div className="text-right">
          <span className={`text-base font-black font-mono leading-none ${
            isPositive ? 'text-green-600' : 'text-red-600'
          }`}>
            {isPositive ? `+${spread.toFixed(2)}` : spread.toFixed(2)}
          </span>
        </div>
      </div>
    </div>
  );
};

export const PriceWatchSection = (arg: ICardSection) => {
    const { apiUrl } = arg
    const { 
      isLoading,
      binanceSymbol,
      mt5Symbol,
      spread,
      binanceMarkPrice,
      mt5MarkPrice
    } = useGetSummaryStreamData(apiUrl)
    
    if (isLoading) {
        return <div className="flex justify-center mt-20 font-medium text-gray-600">Price Watch: Connecting to API...</div>;
    }

    return (
        <>
            {/* Data Rows */}
            <div className="space-y-4">
                <div className="flex justify-between items-end">
                    <div>
                    <p className="text-[10px] font-bold text-blue-500 uppercase tracking-tighter">Binance</p>
                    <p className="text-sm font-medium text-slate-600">{binanceSymbol}</p>
                    </div>
                    <span className="font-mono text-slate-900 font-bold text-base tracking-tight">
                    {binanceMarkPrice.toFixed(2)}
                    </span>
                </div>
                
                <div className="flex justify-between items-end">
                    <div>
                    <p className="text-[10px] font-bold text-emerald-500 uppercase tracking-tighter">MetaTrader 5</p>
                    <p className="text-sm font-medium text-slate-600">{mt5Symbol}</p>
                    </div>
                    <span className="font-mono text-slate-900 font-bold text-base tracking-tight">
                    {mt5MarkPrice.toFixed(2)}
                    </span>
                </div>
            </div>

            <GlassLine />
            <SpreadHighlight spread={spread} />
        </>
    )
}