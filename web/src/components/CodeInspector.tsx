import React, { useState } from 'react';
import { Copy, Check, Terminal } from 'lucide-react';
import { getSqlSource } from '../dataLoader';

export interface CodeFileSpec {
  label: string;
  filePath: string;
}

interface SqlEnginePanelProps {
  files: CodeFileSpec[];
  sqlData: any;
}

export const SqlEnginePanel: React.FC<SqlEnginePanelProps> = ({
  files,
  sqlData,
}) => {
  const [activeIdx, setActiveIdx] = useState(0);
  const [copied, setCopied] = useState(false);

  const currentFile = files[activeIdx] || files[0];
  const code = currentFile ? getSqlSource(sqlData, currentFile.filePath) : '';

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      setTimeout(() => setCopied(false), 1800);
    } catch {
      setCopied(false);
    }
  };

  return (
    <div className="h-full flex flex-col glass-card rounded-xl overflow-hidden">
      <div className="flex flex-wrap items-center justify-between gap-2 px-3.5 py-2 border-b border-slate-200/80 dark:border-white/10 glass-well rounded-none">
        <div className="flex items-center gap-1.5 overflow-x-auto">
          <Terminal className="w-3.5 h-3.5 text-emerald-600 dark:text-emerald-400 shrink-0 mr-1" />
          {files.map((f, idx) => (
            <button
              key={f.filePath}
              type="button"
              onClick={() => setActiveIdx(idx)}
              className={`px-2.5 py-1 text-[11px] font-mono rounded-md transition-all whitespace-nowrap shrink-0 cursor-pointer ${
                activeIdx === idx
                  ? 'bg-white dark:bg-[#1a253d] text-slate-900 dark:text-sky-300 font-semibold shadow-xs border border-slate-200/80 dark:border-white/15'
                  : 'text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white'
              }`}
            >
              {f.label} · {f.filePath}
            </button>
          ))}
        </div>

        <button
          type="button"
          onClick={handleCopy}
          className="inline-flex items-center gap-1.5 px-2.5 py-1 text-[11px] font-mono text-slate-700 dark:text-slate-200 hover:text-slate-950 dark:hover:text-white border border-slate-200 dark:border-white/15 rounded-md bg-white/80 dark:bg-[#141d30]/90 transition-colors whitespace-nowrap shrink-0 cursor-pointer"
        >
          {copied ? (
            <>
              <Check className="w-3.5 h-3.5 text-emerald-600 dark:text-emerald-400" />
              <span>Copied</span>
            </>
          ) : (
            <>
              <Copy className="w-3.5 h-3.5" />
              <span>Copy Source</span>
            </>
          )}
        </button>
      </div>

      <pre
        data-path={currentFile?.filePath}
        className="flex-1 min-h-0 m-0 p-3.5 text-xs font-mono leading-relaxed text-slate-800 dark:text-slate-200 overflow-auto thin-scroll bg-slate-50/40 dark:bg-[#050811]/65">
        {code}
      </pre>
    </div>
  );
};
