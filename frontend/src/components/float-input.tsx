import type { IFloatingLabelInputProps } from "../interfaces/setting-grid.interface";

export const FloatingLabelInput = (arg: IFloatingLabelInputProps) => {
    const { 
        label,
        name,
        value,
        onChange,
        step = "0.01"
    } = arg

  return (
    <div className="w-full mb-4">
      <div className="relative">
        <input
          type="number"
          step={step}
          name={name}
          value={value}
          onChange={onChange}
          className="peer w-full bg-white text-slate-900 text-sm border-2 border-slate-200 rounded-lg px-3 py-2.5 transition-all focus:outline-none focus:border-blue-600 hover:border-slate-300 shadow-sm"
          placeholder=" "
          required
        />
        <label className="absolute cursor-text bg-white px-1 left-2 top-2.5 text-slate-500 text-sm transition-all transform origin-left peer-focus:-top-2.5 peer-focus:left-2 peer-focus:text-xs peer-focus:text-blue-600 peer-focus:font-bold peer-placeholder-shown:top-2.5 peer-placeholder-shown:scale-100 peer-not-placeholder-shown:-top-2.5 peer-not-placeholder-shown:scale-90">
          {label}
        </label>
      </div>
    </div>
  );
};