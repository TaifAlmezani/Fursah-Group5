import { useEffect, useRef, useState } from 'react';
import type { Constraints, DiscoveryResponse, Profile, Recommendation, ViewState } from './types';
import { addInterest, discover, discoverAll, listInterested, removeInterest } from './api/client';
import { loadInitialProfile, persistProfile } from './profile/profile';
import Header from './components/Header';
import { ProfileEditor, ProfileSummary } from './profile/ProfilePanel';
import SearchForm from './opportunities/SearchForm';
import SearchResults from './opportunities/SearchResults';
import OpportunityDetails from './opportunities/OpportunityDetails';
import InterestedPanel from './opportunities/InterestedPanel';

export default function App() {
  const [initial] = useState(loadInitialProfile);
  const [profile, setProfile] = useState<Profile>(initial.profile);
  const [constraints, setConstraints] = useState<Constraints>(initial.constraints);
  const [query, setQuery] = useState('');
  const [view, setView] = useState<ViewState>('initial');
  const [res, setRes] = useState<DiscoveryResponse | null>(null);
  const [editing, setEditing] = useState(false);
  const [details, setDetails] = useState<Recommendation | null>(null);
  const [savedIds, setSavedIds] = useState<Set<string>>(new Set());  // interested (browser-scoped)
  const [showSaved, setShowSaved] = useState(false);
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

  // Load this browser's saved opportunities once, so cards show the correct state on reload.
  useEffect(() => {
    let alive = true;
    listInterested().then(r => { if (alive && r) setSavedIds(new Set(r.opportunity_ids)); });
    return () => { alive = false; };
  }, []);

  // Optimistic toggle; revert if the request fails. opportunity_id is the canonical id.
  async function toggleSave(opportunityId: string) {
    const wasSaved = savedIds.has(opportunityId);
    setSavedIds(prev => {
      const next = new Set(prev);
      if (wasSaved) next.delete(opportunityId); else next.add(opportunityId);
      return next;
    });
    const ok = wasSaved ? await removeInterest(opportunityId) : await addInterest(opportunityId);
    if (!ok) setSavedIds(prev => {
      const next = new Set(prev);
      if (wasSaved) next.add(opportunityId); else next.delete(opportunityId);
      return next;
    });
  }

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
      <Header onEditProfile={() => setEditing(true)} onShowSaved={() => setShowSaved(true)} savedCount={savedIds.size} />
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
          isSaved={id => savedIds.has(id)}
          onToggleSave={toggleSave}
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
      {details && (
        <OpportunityDetails
          rec={details}
          onClose={() => setDetails(null)}
          saved={savedIds.has(details.opportunity_id)}
          onToggleSave={() => toggleSave(details.opportunity_id)}
        />
      )}
      {showSaved && (
        <InterestedPanel
          onClose={() => setShowSaved(false)}
          onOpenDetails={rec => { setShowSaved(false); setDetails(rec); }}
          onRemoved={id => setSavedIds(prev => { const next = new Set(prev); next.delete(id); return next; })}
        />
      )}
    </div>
  );
}
