'use client';

import React, { useState, useEffect } from 'react';
import Link from 'next/link';
import {useRouter} from 'next/navigation';
import ProjectRecords from './ProjectRecords';
import ProjectAssetActions from './ProjectAssetActions';
import { useData, State, rows, Table, Facts, Row } from './DataUI';

export default function ProjectCommand() {
  const router=useRouter();
  const list = useData('/api/v1/projects?page_size=100');
  const [id, setId] = useState('');
  const [tab, setTab] = useState('overview');

  useEffect(() => {
    const requested = new URLSearchParams(window.location.search).get('project');
    if (requested) setId(requested);
  }, []);

  useEffect(() => {
    if (!id && rows(list.data).length) setId(rows(list.data)[0].id);
  }, [id, list.data]);

  const detail = useData(id ? '/api/v1/projects/' + id + '/overview' : null);
  const summary = useData(
    id && tab === 'inventory' ? '/api/v1/projects/' + id + '/inventory-summary' : null
  );
  const d = detail.data;

  return (
    <div className="space-y-5 fade-in">
      {/* Header */}
      <div className="flex flex-wrap justify-between gap-4 items-center">
        <div>
          <p className="text-xs uppercase tracking-widest text-primary mb-2">Projects</p>
          <h1 className="text-2xl font-bold tracking-tight">Project command center</h1>
          <p className="text-sm text-muted-foreground mt-1">
            Cross-domain view of workforce, equipment and inventory per project.
          </p>
        </div>
        <Link className="btn-secondary" href="/workspace/projects">
          All projects
        </Link>
      </div>

      {/* Project selector */}
      <State loading={list.loading} error={list.error} retry={list.reload}>
        <select
          aria-label="Select project"
          className="input-field max-w-lg"
          value={id}
          onChange={e => {
            setId(e.target.value);
            window.history.replaceState(null, '', '?project=' + e.target.value);
          }}
        >
          <option value="">Select a project</option>
          {rows(list.data).map(r => (
            <option key={r.id} value={r.id}>
              {r.name}
            </option>
          ))}
        </select>
        {!rows(list.data).length && (
          <p className="card p-8 text-muted-foreground">No projects available.</p>
        )}
      </State>

      {/* Project detail */}
      {id && (
        <State loading={detail.loading} error={detail.error} retry={detail.reload}>
          {d && (
            <>
              {/* Project header card */}
              <section className="card p-5">
                <div className="flex items-start justify-between gap-4 flex-wrap">
                  <div>
                    <h2 className="text-xl font-bold tracking-tight">{d.project?.name}</h2>
                    <p className="text-sm text-muted-foreground mt-1">
                      {d.client?.name || 'No client recorded'} ·{' '}
                      <span className="font-medium">{d.project?.status}</span>
                    </p>
                  </div>
                  {d.project?.status && (
                    <span
                      className={`badge ${
                        d.project.status === 'ACTIVE' ?'badge-active'
                          : d.project.status === 'MOBILIZING' ?'badge-mobilizing' :'badge-neutral'
                      }`}
                    >
                      {d.project.status}
                    </span>
                  )}
                </div>
                <div className="grid grid-cols-3 gap-4 mt-5">
                  {[
                    ['Assigned people', d.employee_count],
                    ['Assigned assets', d.asset_count],
                    ['Sites', d.sites?.length],
                  ].map(([label, value]) => (
                    <div key={String(label)} className="kpi-card">
                      <div className="kpi-value-sm">{value ?? 0}</div>
                      <div className="kpi-label">{label}</div>
                    </div>
                  ))}
                </div>
              </section>

              {/* Tab navigation */}
              <nav className="tab-nav overflow-x-auto" aria-label="Project sections">
                {['overview', 'workforce', 'equipment', 'inventory', 'sites', 'files & notes'].map(t => (
                  <button
                    key={t}
                    className={'tab-item ' + (tab === t ? 'active' : '')}
                    onClick={() => setTab(t)}
                  >
                    {t.charAt(0).toUpperCase() + t.slice(1)}
                  </button>
                ))}
              </nav>

              {/* Tab content */}
              <section className="card p-5">
                {tab === 'overview' && (
                  <Facts data={{ ...d.project, client: d.client, project_manager: d.project_manager }} />
                )}
                {tab === 'workforce' && <Table data={d.current_employees || []} />}
                {tab === 'equipment' && <div className="space-y-4"><div className="flex justify-end"><ProjectAssetActions projectId={id} onSaved={detail.reload}/></div><Table data={d.current_assets || []} onSelect={row=>router.push('/workspace/assets/'+row.id)}/></div>}
                {tab === 'files & notes' && <ProjectRecords key={id} projectId={id}/>}
                {tab === 'sites' && <Table data={d.sites || []} />}
                {tab === 'inventory' && (
                  <State loading={summary.loading} error={summary.error} retry={summary.reload}>
                    <Facts data={summary.data || {}} />
                    {Object.entries(summary.data || {})
                      .filter(([, v]) => Array.isArray(v) || (v as Row)?.items)
                      .map(([k, v]) => (
                        <div key={k} className="mt-5">
                          <h3 className="font-semibold mb-3 section-header">
                            {k.replace(/_/g, ' ')}
                          </h3>
                          <Table data={rows(v)} />
                        </div>
                      ))}
                  </State>
                )}
              </section>
            </>
          )}
        </State>
      )}
    </div>
  );
}
