import { useEffect, useRef, useState } from 'react';
import type { Constraints, DiscoveryResponse, Profile, Recommendation, ViewState } from './types';
import { discover, discoverAll } from './api/client';
import { loadInitialProfile, persistProfile } from './profile/profile';
import Header from './components/Header';
import { ProfileEditor, ProfileSummary } from './profile/ProfilePanel';
import SearchForm from './opportunities/SearchForm';
import SearchResults from './opportunities/SearchResults';
import OpportunityDetails from './opportunities/OpportunityDetails';

export default function App() {
  const [initial] = useState(loadInitialProfile);
  const [profile, setProfile] = useState<Profile>(initial.profile);
  const [constraints, setConstraints] = useState<Constraints>(initial.constraints);
  const [query, setQuery] = useState('');
  const [view, setView] = useState<ViewState>('initial');
  const [res, setRes] = useState<DiscoveryResponse | null>(null);
  const [editing, setEditing] = useState(false);
  const [details, setDetails] = useState<Recommendation | null>(null);
  const [more, setMore] = useState<Recommendation[]>([]);      // extra recs from show-more
  const [browseTotal, setBrowseTotal] = useState<number | null>(null);
  const [browseLoading, setBrowseLoading] = useState(false);
  const queryRef = useRef<HTMLTextAreaElement>(null);
  const seq = useRef(0);
  const pending = useRef(false);
  const controller = useRef<AbortController | null>(null);
  const submitted = useRef<{ query: string; profile: Profile; constraints: Constraints } | null>(null);
  const lastResolution = useRef<'profile' | 'query' | undefined>(undefined);
  useEffect(() => () => { ++seq.current; controller.current?.abort(); }, []);

  useEffect(() => persistProfile(profile, constraints), [profile, constraints]);

  const missing = view === 'needs_info' ? res?.missing_fields ?? [] : [];

  function resetBrowse() {
    setMore([]);
    setBrowseTotal(null);
    setBrowseLoading(false);
  }

  function invalidateSearch() {
    ++seq.current;
    controller.current?.abort();
    pending.current = false;
    submitted.current = null;
    setRes(null);
    setDetails(null);
    setView('initial');
    resetBrowse();
  }

  // "Show more / show all": page through the full ranking for the same submitted search.
  async function loadMore(all: boolean) {
    if (!submitted.current || browseLoading) return;
    const shownCount = (res?.recommendations.length ?? 0) + more.length;
    setBrowseLoading(true);
    try {
      const page = await discoverAll(
        { request_id: null, ...submitted.current, constraint_resolution: lastResolution.current },
        shownCount, all ? 1000 : 3,
      );
      if (!page) return;
      const seen = new Set([...(res?.recommendations ?? []), ...more].map(r => r.opportunity_id));
      const fresh = page.recommendations.filter(r => !seen.has(r.opportunity_id));
      setMore(m => [...m, ...fresh]);
      setBrowseTotal(page.total);
    } finally {
      setBrowseLoading(false);
    }
  }

  async function runDiscover(p: Profile = profile, c: Constraints = constraints, resolution?: 'profile' | 'query') {
    if (pending.current) return;
    const snapshot = resolution ? submitted.current : { query: query.trim(), profile: p, constraints: c };
    if (!snapshot) return;
    const q = snapshot.query;
    if (!q) { queryRef.current?.focus(); return; }
    // Results and resolution actions share the exact submitted input snapshot.
    submitted.current = structuredClone(snapshot);
    lastResolution.current = resolution;
    resetBrowse();
    const id = ++seq.current;
    controller.current?.abort();
    controller.current = new AbortController();
    pending.current = true;
    setView('loading');
    setRes(null);
    try {
      const r = await discover({ request_id: null, ...submitted.current, constraint_resolution: resolution }, controller.current.signal);
      if (id !== seq.current) return;
      setRes(r);
      setView(r.status);
    } catch {
      if (id !== seq.current) return;
      setRes({ request_id: '', status: 'error', message: 'تعذّر إكمال البحث. لم تفقد بيانات ملفك.', recommendations: [], missing_fields: [], error_code: 'FURSAH_CLIENT_ERROR' });
      setView('error');
    } finally {
      if (id === seq.current) pending.current = false;
    }
  }

  return (
    <div className="app" dir="rtl" lang="ar">
      <Header onEditProfile={() => setEditing(true)} />
      <main className="container main">
        {initial.notice && <p className="notice" role="status">{initial.notice}</p>}
        <ProfileSummary profile={profile} constraints={constraints} missing={missing} onEdit={() => setEditing(true)} />
        <SearchForm
          inputRef={queryRef}
          query={query}
          onChange={value => { invalidateSearch(); setQuery(value); }}
          onSubmit={() => runDiscover()}
          loading={view === 'loading'}
        />
        <SearchResults
          view={view}
          res={res}
          more={more}
          browseTotal={browseTotal}
          browseLoading={browseLoading}
          onShowMore={() => loadMore(false)}
          onShowAll={() => loadMore(true)}
          onEditProfile={() => setEditing(true)}
          onResolve={choice => runDiscover(profile, constraints, choice)}
          onRetry={() => runDiscover()}
          onFocusQuery={() => queryRef.current?.focus()}
          onOpenDetails={setDetails}
        />
      </main>

      {editing && (
        <ProfileEditor
          profile={profile}
          constraints={constraints}
          missing={missing}
          onClose={() => setEditing(false)}
          onSave={(p, c, andSearch) => {
            invalidateSearch();
            setProfile(p);
            setConstraints(c);
            setEditing(false);
            if (andSearch) runDiscover(p, c);
          }}
        />
      )}
      {details && <OpportunityDetails rec={details} onClose={() => setDetails(null)} />}
    </div>
  );
}
