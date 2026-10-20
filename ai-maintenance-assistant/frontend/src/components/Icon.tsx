const paths = {
  tool: 'M14.7 6.3a5.5 5.5 0 0 0-7 7L3 18a2.1 2.1 0 0 0 3 3l4.7-4.7a5.5 5.5 0 0 0 7-7l-3.4 3.4-3-3 3.4-3.4Z',
  ticket: 'M4 4h16v5a3 3 0 0 0 0 6v5H4v-5a3 3 0 0 0 0-6V4Zm10 3v2m0 3v2m0 3v1',
  arrow: 'M19 12H5m6-6-6 6 6 6',
  bolt: 'm13 2-9 12h7l-1 8 10-13h-7l0-7Z',
  snow: 'M12 3v18M4.2 7.5l15.6 9M4.2 16.5l15.6-9M9 4l3 3 3-3M9 20l3-3 3 3',
  printer: 'M7 8V3h10v5M7 17H4V9h16v8h-3M7 14h10v7H7v-7Zm10-3h.01',
  pin: 'M19 10c0 5-7 11-7 11S5 15 5 10a7 7 0 1 1 14 0ZM12 7a3 3 0 1 0 0 6 3 3 0 0 0 0-6Z',
  shield: 'm12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6l8-3Zm-4 9 3 3 5-6',
  spark: 'm12 3 2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5L12 3Z',
  close: 'm6 6 12 12M6 18 18 6',
  list: 'M9 6h11M9 12h11M9 18h11M4 6h.01M4 12h.01M4 18h.01',
  check: 'm5 12 4 4L19 6',
  info: 'M12 11v6m0-10h.01M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0Z',
  plus: 'M12 5v14M5 12h14',
} as const;

export type IconName = keyof typeof paths;

export default function Icon({ name, className = '' }: { name: IconName; className?: string }) {
  return <svg className={`icon ${className}`} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false"><path d={paths[name]} /></svg>;
}
