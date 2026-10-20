import type { EvidenceSource } from '../../types/maintenance';
import { Field } from './ResultCard';

const sourceLabels: Record<string, string> = {
  'air_conditioning.md': 'إجراءات التكييف',
  'printers.md': 'إجراءات الطابعات',
  'plumbing.md': 'إجراءات السباكة',
  'electrical.md': 'السلامة الكهربائية',
};

export default function EvidenceReferences({ evidence }: { evidence?: EvidenceSource[] }) {
  if (!evidence?.length) return null;
  return (
    <Field label="مرجع التوصية">
      <ul>{evidence.map(item => (
        <li key={item.procedure_id}>{sourceLabels[item.source] ?? item.source} — {item.section}</li>
      ))}</ul>
    </Field>
  );
}
