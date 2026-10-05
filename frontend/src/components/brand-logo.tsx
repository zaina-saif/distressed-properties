export function DistressSaleLogo() {
  return (
    <div className="relative flex h-11 w-11 shrink-0 items-center justify-center overflow-hidden rounded-[14px] bg-slate-950 text-white shadow-[0_6px_18px_rgba(15,23,42,0.22)] ring-1 ring-slate-900/10">
      <svg viewBox="0 0 48 48" className="h-10 w-10" aria-hidden="true">
        <path d="M9 23.5 24 11l15 12.5" fill="none" stroke="currentColor" strokeWidth="3.2" strokeLinecap="round" strokeLinejoin="round" />
        <path d="M13.5 21.5V37h21V21.5" fill="none" stroke="currentColor" strokeWidth="3.2" strokeLinejoin="round" />
        <path d="m26 18-4 7h5l-4 8" fill="none" stroke="#2dd4bf" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" />
        <path d="M31.5 13.5 37 19" fill="none" stroke="#f59e0b" strokeWidth="2.5" strokeLinecap="round" />
      </svg>
      <span className="absolute bottom-1.5 right-1.5 h-2 w-2 rounded-full bg-amber-400 ring-2 ring-slate-950" />
    </div>
  );
}
