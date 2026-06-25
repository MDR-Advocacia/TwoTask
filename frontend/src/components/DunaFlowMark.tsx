// Marca DunaFlow — símbolo de onda (duna) + wordmark.
// Usa currentColor, então herda a cor do texto do container (navy no fundo
// claro do sidebar/login, branco sobre o hero escuro). Reaproveitado no
// sidebar, no drawer mobile, na tela de login e no hero da landing.

interface DunaFlowMarkProps {
  size?: 'sm' | 'md' | 'lg';
  className?: string;
}

const SIZES: Record<'sm' | 'md' | 'lg', { icon: number; text: string; gap: string }> = {
  sm: { icon: 26, text: 'text-sm tracking-[0.08em]', gap: 'gap-2' },
  md: { icon: 32, text: 'text-xl tracking-[0.07em]', gap: 'gap-2.5' },
  lg: { icon: 52, text: 'text-3xl tracking-[0.06em]', gap: 'gap-3' },
};

export function DunaFlowMark({ size = 'md', className = '' }: DunaFlowMarkProps) {
  const s = SIZES[size];
  return (
    <span className={`inline-flex items-center whitespace-nowrap ${s.gap} ${className}`}>
      <svg
        className="shrink-0"
        width={s.icon}
        height={Math.round(s.icon * 0.6)}
        viewBox="0 0 40 24"
        fill="none"
        aria-hidden="true"
      >
        <path
          d="M2,15 C9,8 13,8 20,13 C26,17 31,16 38,10"
          stroke="currentColor"
          strokeWidth="3"
          strokeLinecap="round"
        />
        <path
          d="M3,21 C10,15 14,15 20,19 C25,22 30,21 37,16"
          stroke="currentColor"
          strokeWidth="2.4"
          strokeLinecap="round"
          opacity="0.7"
        />
      </svg>
      <span className={`${s.text} font-semibold leading-none`}>
        DUNA<span className="font-normal opacity-80">FLOW</span>
      </span>
    </span>
  );
}
