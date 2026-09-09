import React from 'react';
import AppLogo from '@/components/ui/AppLogo';

const FEATURES = [
  { id: 'bp-feat-workforce', text: 'Workforce & rotation management' },
  { id: 'bp-feat-fleet', text: 'Equipment fleet command center' },
  { id: 'bp-feat-inventory', text: 'Full inventory lifecycle tracking' },
  { id: 'bp-feat-projects', text: 'Cross-domain project visibility' },
];

export default function BrandPanel() {
  return (
    <div className="hidden lg:flex flex-col w-[480px] xl:w-[520px] flex-shrink-0 gradient-brand text-white relative overflow-hidden">
      {/* Background grid decoration */}
      <div
        className="absolute inset-0 opacity-5"
        style={{
          backgroundImage: `repeating-linear-gradient(0deg, transparent, transparent 40px, rgba(255,255,255,0.3) 40px, rgba(255,255,255,0.3) 41px), repeating-linear-gradient(90deg, transparent, transparent 40px, rgba(255,255,255,0.3) 40px, rgba(255,255,255,0.3) 41px)`,
        }}
      />

      <div className="relative z-10 flex flex-col h-full p-10 xl:p-12">
        {/* Logo */}
        <div className="flex items-center gap-3 mb-12">
          <AppLogo size={36} />
          <div>
            <p className="text-lg font-bold leading-tight">Cestos Operations</p>
            <p className="text-xs text-blue-200 font-400">Field Operations Command Platform</p>
          </div>
        </div>

        {/* Hero copy */}
        <div className="mb-10">
          <h1 className="text-3xl xl:text-4xl font-700 leading-tight mb-4" style={{ letterSpacing: '-0.02em' }}>
            One platform for your entire operations.
          </h1>
          <p className="text-blue-200 text-base leading-relaxed">
            Manage workforce, equipment fleet, and inventory across all active drill sites from a single command center.
          </p>
        </div>

        {/* Feature list */}
        <div className="space-y-3 mb-10">
          {FEATURES?.map(f => (
            <div key={f?.id} className="flex items-center gap-3">
              <div className="w-5 h-5 rounded-full border-2 border-blue-300 flex items-center justify-center flex-shrink-0">
                <div className="w-2 h-2 rounded-full bg-blue-300" />
              </div>
              <span className="text-sm text-blue-100 font-400">{f?.text}</span>
            </div>
          ))}
        </div>

        <div className="mt-auto border-t border-white/20 pt-6"><p className="text-sm text-blue-100">Built for your people, your equipment, and every site you operate.</p></div>
      </div>
    </div>
  );
}
