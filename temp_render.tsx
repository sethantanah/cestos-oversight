      case 'EXPENSES': {
        const { totalExp, count, avgClaim, maxClaim, totalItemsCount } = expenseIntelligenceMetrics;

        return (
          <div className="space-y-6 w-full">
            {renderFilterBar()}

            {/* Header & Submit Button */}
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
              <div>
                <h2 className="font-bold text-xl text-foreground flex items-center gap-2">
                  <DollarSign className="h-6 w-6 text-violet-600" /> Operational Expenses &amp; Purchasing Intelligence
                </h2>
                <p className="text-xs text-muted-foreground">
                  Expenditure tracking, vendor analytics, frequency intelligence, and expense claim management.
                </p>
              </div>
              <button
                type="button"
                onClick={() => setShowExpenseModal(true)}
                className="px-4 py-2 bg-violet-600 hover:bg-violet-700 text-white rounded-xl text-xs font-bold shadow-sm transition flex items-center gap-1.5 shrink-0"
              >
                <Plus size={15} /> Submit Operational Expense Claim
              </button>
            </div>

            {/* KPI Summary Cards */}
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
              <div className="p-4 bg-card border rounded-2xl shadow-xs space-y-1">
                <span className="text-[11px] font-bold text-muted-foreground uppercase tracking-wider block">Total Expenditure</span>
                <p className="text-2xl font-black text-violet-600">${totalExp.toLocaleString()}</p>
                <span className="text-[10px] text-muted-foreground">{count} claims submitted</span>
              </div>
              <div className="p-4 bg-card border rounded-2xl shadow-xs space-y-1">
                <span className="text-[11px] font-bold text-muted-foreground uppercase tracking-wider block">Average Claim Value</span>
                <p className="text-2xl font-black text-foreground">${Math.round(avgClaim).toLocaleString()}</p>
                <span className="text-[10px] text-muted-foreground">Per expense voucher</span>
              </div>
              <div className="p-4 bg-card border rounded-2xl shadow-xs space-y-1">
                <span className="text-[11px] font-bold text-muted-foreground uppercase tracking-wider block">Highest Single Claim</span>
                <p className="text-2xl font-black text-emerald-600">${maxClaim.toLocaleString()}</p>
                <span className="text-[10px] text-muted-foreground">Peak expenditure item</span>
              </div>
              <div className="p-4 bg-card border rounded-2xl shadow-xs space-y-1">
                <span className="text-[11px] font-bold text-muted-foreground uppercase tracking-wider block">Line Items Purchased</span>
                <p className="text-2xl font-black text-amber-600">{totalItemsCount}</p>
                <span className="text-[10px] text-muted-foreground">Purchased items count</span>
              </div>
            </div>

            {/* 1. Operational Expenditure & Expense Trend (Full Row FIRST) */}
            <div className="p-5 bg-card border rounded-2xl shadow-sm space-y-3">
              <div className="flex items-center justify-between border-b pb-3 border-border">
                <div className="flex items-center gap-2">
                  <div className="p-2 rounded-xl bg-violet-100 dark:bg-violet-950 text-violet-600">
                    <TrendingUp size={18} />
                  </div>
                  <div>
                    <h3 className="font-bold text-sm text-foreground">Operational Expenditure &amp; Expense Trend ($)</h3>
                    <p className="text-[11px] text-muted-foreground">Daily breakdown of total operational expenses ($) and approved expenditure</p>
                  </div>
                </div>
              </div>

              {expenseTimeSeriesData.length === 0 ? (
                <EmptyState message="No expense time-series data available for the selected range." />
              ) : (
                <div className="h-72 w-full pt-2">
                  <ResponsiveContainer width="100%" height="100%">
                    <ComposedChart data={expenseTimeSeriesData} margin={{ top: 10, right: 20, left: 0, bottom: 0 }}>
                      <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="currentColor" className="text-border opacity-40" />
                      <XAxis dataKey="date" tick={{ fontSize: 11 }} />
                      <YAxis stroke="#8b5cf6" tick={{ fontSize: 11 }} />
                      <Tooltip
                        contentStyle={{ backgroundColor: 'var(--background)', borderRadius: '12px', border: '1px solid var(--border)' }}
                        formatter={(val: any) => [`$${Number(val).toLocaleString()}`]}
                      />
                      <Legend />
                      <Bar dataKey="totalCost" fill="#8b5cf6" radius={[6, 6, 0, 0]} name="Total Expense Requested ($)" />
                      <Line type="monotone" dataKey="approvedCost" stroke="#10b981" strokeWidth={3} dot={{ r: 4 }} name="Approved Expenditure ($)" />
                    </ComposedChart>
                  </ResponsiveContainer>
                </div>
              )}
            </div>

            {/* 2. Purchasing Intelligence Bar Charts Grid (3 Columns SECOND) */}
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
              {/* Top Cost Items */}
              <div className="p-4 bg-card border rounded-2xl shadow-xs space-y-3">
                <h4 className="font-bold text-xs uppercase tracking-wider text-muted-foreground flex items-center gap-1.5">
                  <DollarSign size={14} className="text-violet-600" /> Top Cost Items ($)
                </h4>
                {topItemsByCostData.length === 0 ? (
                  <p className="text-xs text-muted-foreground py-6 text-center">No cost item data</p>
                ) : (
                  <div className="h-56 w-full">
                    <ResponsiveContainer width="100%" height="100%">
                      <BarChart data={topItemsByCostData} layout="vertical" margin={{ top: 5, right: 15, left: 40, bottom: 5 }}>
                        <XAxis type="number" tick={{ fontSize: 9 }} />
                        <YAxis type="category" dataKey="name" tick={{ fontSize: 10 }} width={70} />
                        <Tooltip formatter={(val: any) => [`$${Number(val).toLocaleString()}`, 'Total Cost']} />
                        <Bar dataKey="totalCost" fill="#8b5cf6" radius={[0, 4, 4, 0]} />
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                )}
              </div>

              {/* Most Frequent Items */}
              <div className="p-4 bg-card border rounded-2xl shadow-xs space-y-3">
                <h4 className="font-bold text-xs uppercase tracking-wider text-muted-foreground flex items-center gap-1.5">
                  <Package size={14} className="text-emerald-600" /> Most Frequent Items
                </h4>
                {topItemsByFrequencyData.length === 0 ? (
                  <p className="text-xs text-muted-foreground py-6 text-center">No item frequency data</p>
                ) : (
                  <div className="h-56 w-full">
                    <ResponsiveContainer width="100%" height="100%">
                      <BarChart data={topItemsByFrequencyData} layout="vertical" margin={{ top: 5, right: 15, left: 40, bottom: 5 }}>
                        <XAxis type="number" tick={{ fontSize: 9 }} />
                        <YAxis type="category" dataKey="name" tick={{ fontSize: 10 }} width={70} />
                        <Tooltip formatter={(val: any) => [`${Number(val)} times`, 'Purchase Frequency']} />
                        <Bar dataKey="frequency" fill="#10b981" radius={[0, 4, 4, 0]} />
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                )}
              </div>

              {/* Vendor Expenditure */}
              <div className="p-4 bg-card border rounded-2xl shadow-xs space-y-3">
                <h4 className="font-bold text-xs uppercase tracking-wider text-muted-foreground flex items-center gap-1.5">
                  <Building2 size={14} className="text-amber-600" /> Vendor Breakdown ($)
                </h4>
                {topVendorData.length === 0 ? (
                  <p className="text-xs text-muted-foreground py-6 text-center">No vendor data</p>
                ) : (
                  <div className="h-56 w-full">
                    <ResponsiveContainer width="100%" height="100%">
                      <BarChart data={topVendorData} layout="vertical" margin={{ top: 5, right: 15, left: 40, bottom: 5 }}>
                        <XAxis type="number" tick={{ fontSize: 9 }} />
                        <YAxis type="category" dataKey="vendor" tick={{ fontSize: 10 }} width={70} />
                        <Tooltip formatter={(val: any) => [`$${Number(val).toLocaleString()}`, 'Vendor Spend']} />
                        <Bar dataKey="totalCost" fill="#f59e0b" radius={[0, 4, 4, 0]} />
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                )}
              </div>
            </div>

            {/* 3. Submitted Expenses & Finance Status Table (FIRST Table) */}
            <div className="space-y-3">
              <h3 className="font-bold text-base text-foreground flex items-center justify-between">
                <span>Submitted Operational Expense Claims &amp; Status</span>
                <span className="text-xs text-muted-foreground font-normal">{scopedOperationalExpenseRequests.length} claims</span>
              </h3>
              {scopedOperationalExpenseRequests.length === 0 ? (
                <EmptyState message="No operational expense claims submitted yet." />
              ) : (
                <div className="overflow-x-auto rounded-2xl border bg-card shadow-xs">
                  <table className="w-full text-xs">
                    <thead className="bg-muted/50 border-b">
                      <tr>
                        {['Date', 'Submitted By', 'Ref # / Payee', 'Payment Method', 'Total Amount', 'Status', 'Receipt Docket', 'Actions'].map((h) => (
                          <th key={h} className="px-4 py-3 text-left font-bold text-muted-foreground uppercase tracking-wider">{h}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody className="divide-y">
                      {scopedOperationalExpenseRequests.map((exp) => {
                        const cost = Number(exp.total_cost || exp.amount || 0);
                        const fileName = exp.receipt_file_name || exp.attachment;
                        const sName = exp.submitted_by_name || exp.submitted_by?.full_name || (exp.submitted_by?.first_name ? `${exp.submitted_by.first_name} ${exp.submitted_by.last_name || ''}`.trim() : null) || exp.created_by_name || (user?.first_name ? `${user.first_name} ${user.last_name || ''}`.trim() : 'Operations Supervisor');
                        const sPos = exp.submitted_by_position || exp.submitted_by_title || exp.submitted_by?.job_title || exp.submitted_by?.role || (user?.is_superuser ? 'Operations Director' : user?.portal_type ? `${user.portal_type.replace('_', ' ')} Admin` : 'Field Administrator');
                        const sEmail = exp.submitted_by_email || exp.submitted_by?.email || exp.email || user?.email || 'operations@cestos.com';

                        return (
                          <tr key={exp.id} className="hover:bg-muted/30 transition">
                            <td className="px-4 py-3 font-mono">{exp.expense_date ? new Date(exp.expense_date).toLocaleDateString() : '—'}</td>
                            <td className="px-4 py-3 space-y-0.5">
                              <div className="font-bold text-foreground flex items-center gap-1">
                                <User size={12} className="text-violet-600 shrink-0" />
                                <span>{sName}</span>
                              </div>
                              <div className="text-[11px] text-muted-foreground font-medium flex items-center gap-1">
                                <Briefcase size={11} className="text-slate-400 shrink-0" />
                                <span>{sPos}</span>
                              </div>
                              <div>
                                <a
                                  href={`mailto:${sEmail}`}
                                  onClick={(e) => e.stopPropagation()}
                                  className="inline-flex items-center gap-1 text-violet-600 dark:text-violet-400 hover:text-violet-800 dark:hover:text-violet-300 font-mono text-[11px] font-bold underline"
                                  title={`Send email to ${sName}`}
                                >
                                  <Mail size={11} className="shrink-0" />
                                  {sEmail}
                                </a>
                              </div>
                            </td>
                            <td className="px-4 py-3 font-bold text-foreground">{exp.pay_to_name || exp.reference_number || exp.id.slice(0, 8)}</td>
                            <td className="px-4 py-3 font-medium text-muted-foreground">{exp.payment_method || 'MOBILE_MONEY'}</td>
                            <td className="px-4 py-3 font-bold text-violet-600">${cost.toLocaleString()}</td>
                            <td className="px-4 py-3"><StatusBadge status={exp.status || 'SUBMITTED'} /></td>
                            <td className="px-4 py-3">
                              {fileName ? (
                                <button
                                  type="button"
                                  onClick={() => setViewingExpense(exp)}
                                  className="inline-flex items-center gap-1.5 text-violet-600 hover:text-violet-800 font-bold underline text-xs"
                                >
                                  <Paperclip size={13} /> View Docket
                                </button>
                              ) : (
                                <span className="text-muted-foreground text-[11px]">No docket</span>
                              )}
                            </td>
                            <td className="px-4 py-3">
                              <button
                                type="button"
                                onClick={() => {
                                  setViewingExpense(exp);
                                }}
                                className="p-1.5 rounded-lg bg-muted hover:bg-violet-100 text-violet-700 transition"
                                title="View Claim Details"
                              >
                                <Eye size={14} />
                              </button>
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}
            </div>

            {/* 4. Site Operational Cost Subledger Log (SECOND Table) */}
            <div className="space-y-3">
              <h3 className="font-bold text-base text-foreground flex items-center justify-between">
                <span>Site Operational Cost Subledger Log</span>
                <span className="text-xs text-muted-foreground font-normal">{scopedExpenses.length} entries</span>
              </h3>
              {scopedExpenses.length === 0 ? (
                <EmptyState message="No cost subledger entries found." />
              ) : (
                <div className="overflow-x-auto rounded-2xl border bg-card shadow-xs">
                  <table className="w-full text-xs">
                    <thead className="bg-muted/50 border-b">
                      <tr>
                        {['Entry Date', 'Category', 'Description', 'Amount', 'Currency', 'Project'].map((h) => (
                          <th key={h} className="px-4 py-3 text-left font-bold text-muted-foreground uppercase tracking-wider">{h}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody className="divide-y">
                      {scopedExpenses.map((c, i) => (
                        <tr key={c.id || i} className="hover:bg-muted/30 transition">
                          <td className="px-4 py-3 font-mono">{c.entry_date || c.created_at?.slice(0, 10) || '—'}</td>
                          <td className="px-4 py-3 font-bold">{c.cost_category || 'OPERATIONAL'}</td>
                          <td className="px-4 py-3 text-muted-foreground">{c.description || '—'}</td>
                          <td className="px-4 py-3 font-bold text-foreground">${Number(c.amount || 0).toLocaleString()}</td>
                          <td className="px-4 py-3 font-mono text-muted-foreground">{c.currency || 'USD'}</td>
                          <td className="px-4 py-3 text-muted-foreground">
                            {projects.find((p) => String(p.id) === String(c.project_id))?.name || c.project_id || '—'}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          </div>
        );
      }
    }
  }

  // ─── Layout (Matching Field Admin Top Navigation Header Layout) ─────────────

  return (
    <div className="min-h-screen bg-slate-50 dark:bg-slate-950 flex flex-col font-sans">
      {/* Top Header Bar */}
      <header className="bg-white dark:bg-slate-900 border-b border-slate-200 dark:border-slate-800 sticky top-0 z-40 shadow-xs">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-3 flex items-center justify-between gap-4">
          {/* Logo & Portal Title */}
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-xl bg-violet-600 flex items-center justify-center text-white shadow-sm shrink-0">
              <DollarSign size={20} />
            </div>
            <div>
              <h1 className="font-bold text-base leading-tight text-slate-900 dark:text-white">
                Finance Portal
              </h1>
              <p className="text-[11px] text-violet-600 dark:text-violet-400 font-medium">Financial Operations &amp; Intelligence</p>
            </div>
          </div>

          {/* Right Header Actions */}
          <div className="flex items-center gap-3">
            <button
              onClick={reload}
              className="p-2 text-slate-500 hover:text-slate-800 dark:hover:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-800 rounded-lg transition"
              title="Refresh Portal Data"
            >
              <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin text-violet-600' : ''}`} />
            </button>

            <button
              onClick={() => void signOut()}
              className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white hover:bg-slate-100 dark:hover:bg-slate-800 rounded-lg transition"
            >
              <LogOut size={15} /> <span className="hidden sm:inline">Sign out</span>
            </button>

            <button className="sm:hidden p-1.5 text-slate-600" onClick={() => setMobileMenuOpen(!mobileMenuOpen)}>
              {mobileMenuOpen ? <X size={22} /> : <Menu size={22} />}
            </button>
          </div>
        </div>

        {/* Top Horizontal Navigation Bar in Requested Order */}
        <nav className={`border-t border-slate-100 dark:border-slate-800 ${mobileMenuOpen ? 'block' : 'hidden sm:block'}`}>
          <div className="flex overflow-x-auto scrollbar-hide px-4 sm:px-6 lg:px-8 max-w-7xl mx-auto">
            {navItems.map((t) => {
              const Icon = t.icon;
              const active = activeTab === t.id;
              return (
                <button
                  key={t.id}
                  onClick={() => { setActiveTab(t.id); setMobileMenuOpen(false); }}
                  className={`flex items-center gap-2 px-3 py-2.5 text-xs font-bold whitespace-nowrap border-b-2 transition-colors ${
                    active
                      ? 'border-violet-600 text-violet-700 dark:text-violet-400 bg-violet-50/50 dark:bg-violet-950/30'
                      : 'border-transparent text-slate-500 hover:text-slate-800 dark:hover:text-slate-200 hover:bg-slate-50 dark:hover:bg-slate-900'
                  }`}
                >
                  <Icon size={15} />
                  <span>{t.label}</span>
                  {t.id === 'OPERATIONAL_EXPENSES' && unresolvedClaimsCount > 0 && (
                    <span className="ml-1 inline-flex items-center justify-center px-1.5 py-0.5 rounded-full text-[10px] font-extrabold bg-amber-500 text-white shadow-xs animate-pulse">
                      {unresolvedClaimsCount}
                    </span>
                  )}
                </button>
              );
            })}
          </div>
        </nav>
      </header>

      {/* Alert Banner */}
      {banner && (
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 mt-4 w-full">
          <Banner message={banner.message} type={banner.type} onClose={() => setBanner(null)} />
        </div>
      )}

      {/* Main Content Area */}
      <main className="flex-1 px-4 sm:px-6 lg:px-8 py-4 max-w-7xl mx-auto w-full space-y-4">
        {renderContent()}
      </main>

      {/* MODALS */}
      {showExpenseModal && (
        <OperationalExpenseSubmissionModal
          onClose={() => setShowExpenseModal(false)}
          onSubmitted={() => { setShowExpenseModal(false); reload(); setBanner({ type: 'success', message: 'Operational Expense claim submitted successfully.' }); }}
        />
      )}

      {/* Create Purchase Order Modal */}
      {showAddPoModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-xs overflow-y-auto">
          <div className="bg-card border rounded-2xl p-6 max-w-xl w-full space-y-4 shadow-2xl my-8">
            <div className="flex items-center justify-between border-b pb-3 border-border">
              <h3 className="font-bold text-base flex items-center gap-2 text-foreground">
                <ShoppingBag className="h-5 w-5 text-violet-600" /> Create Purchase Order
              </h3>
              <button onClick={() => setShowAddPoModal(false)} className="p-1 rounded-lg hover:bg-muted text-muted-foreground"><X size={18} /></button>
            </div>

            <form onSubmit={handleCreatePo} className="space-y-4">
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-bold text-foreground mb-1">Vendor / Supplier Name *</label>
                  <input
                    type="text"
                    required
                    placeholder="e.g. Caterpillar Machinery Corp"
                    value={newPoForm.supplier_name}
                    onChange={(e) => setNewPoForm({ ...newPoForm, supplier_name: e.target.value })}
                    className="w-full p-2.5 border rounded-xl bg-background text-xs"
                  />
                </div>
                <div>
                  <label className="block text-xs font-bold text-foreground mb-1">Project Assignment</label>
                  <select
                    value={newPoForm.project_id}
                    onChange={(e) => setNewPoForm({ ...newPoForm, project_id: e.target.value })}
                    className="w-full p-2.5 border rounded-xl bg-background text-xs"
                  >
                    <option value="">Organization-Wide (All Projects)</option>
                    {projects.map((p) => (
                      <option key={p.id} value={p.id}>{p.name}</option>
                    ))}
                  </select>
                </div>
              </div>

              <div>
                <label className="block text-xs font-bold text-foreground mb-1">Currency &amp; Notes</label>
                <div className="grid grid-cols-3 gap-2">
                  <select
                    value={newPoForm.currency}
                    onChange={(e) => setNewPoForm({ ...newPoForm, currency: e.target.value })}
                    className="p-2.5 border rounded-xl bg-background text-xs font-bold"
                  >
                    <option value="USD">USD ($)</option>
                    <option value="EUR">EUR (€)</option>
                    <option value="GBP">GBP (£)</option>
                    <option value="ZAR">ZAR (R)</option>
                  </select>
                  <input
                    type="text"
                    placeholder="Purchase Order Notes / Specifications"
                    value={newPoForm.notes}
                    onChange={(e) => setNewPoForm({ ...newPoForm, notes: e.target.value })}
                    className="col-span-2 p-2.5 border rounded-xl bg-background text-xs"
                  />
                </div>
              </div>

              <div>
                <label className="block text-xs font-bold text-foreground mb-1">Attachment / Quote Docket (Optional)</label>
                <input
                  type="file"
                  onChange={(e) => setPoAttachmentFile(e.target.files?.[0] || null)}
                  className="w-full p-2 border rounded-xl bg-background text-xs text-muted-foreground file:mr-3 file:py-1 file:px-2.5 file:rounded-lg file:border-0 file:text-xs file:font-bold file:bg-violet-50 file:text-violet-700 hover:file:bg-violet-100"
                />
                {poAttachmentFile && (
                  <p className="text-[11px] text-violet-600 font-medium mt-1 flex items-center gap-1">
                    <Paperclip size={12} /> {poAttachmentFile.name} ({(poAttachmentFile.size / 1024).toFixed(1)} KB)
                  </p>
                )}
              </div>

              {/* Line Items List */}
              <div className="space-y-2 border-t pt-3">
                <div className="flex items-center justify-between">
                  <label className="text-xs font-bold text-foreground uppercase tracking-wider">Purchase Order Line Items</label>
                  <button
                    type="button"
                    onClick={() => setNewPoForm({
                      ...newPoForm,
                      items: [...newPoForm.items, { description: '', quantity_ordered: 1, unit_price: 0 }],
                    })}
                    className="text-xs font-bold text-violet-600 hover:underline flex items-center gap-1"
                  >
                    <Plus size={13} /> Add Item
                  </button>
                </div>

                {newPoForm.items.map((it, idx) => (
                  <div key={idx} className="flex items-center gap-2 p-2 border rounded-xl bg-muted/40">
                    <input
                      type="text"
                      placeholder="Item Description"
                      value={it.description}
                      onChange={(e) => {
                        const updated = [...newPoForm.items];
                        updated[idx].description = e.target.value;
                        setNewPoForm({ ...newPoForm, items: updated });
                      }}
                      className="flex-1 p-1.5 border rounded-lg bg-background text-xs"
                    />
                    <input
                      type="number"
                      placeholder="Qty"
                      min="1"
                      value={it.quantity_ordered}
                      onChange={(e) => {
                        const updated = [...newPoForm.items];
                        updated[idx].quantity_ordered = Number(e.target.value) || 1;
                        setNewPoForm({ ...newPoForm, items: updated });
                      }}
                      className="w-16 p-1.5 border rounded-lg bg-background text-xs font-mono text-center"
                    />
                    <input
                      type="number"
                      placeholder="Price"
                      min="0"
                      value={it.unit_price}
                      onChange={(e) => {
                        const updated = [...newPoForm.items];
                        updated[idx].unit_price = Number(e.target.value) || 0;
                        setNewPoForm({ ...newPoForm, items: updated });
                      }}
                      className="w-20 p-1.5 border rounded-lg bg-background text-xs font-mono text-right"
                    />
                    {newPoForm.items.length > 1 && (
                      <button
                        type="button"
                        onClick={() => {
                          const updated = newPoForm.items.filter((_, i) => i !== idx);
                          setNewPoForm({ ...newPoForm, items: updated });
                        }}
                        className="p-1 text-red-500 hover:text-red-700"
                      >
                        <Trash2 size={14} />
                      </button>
                    )}
                  </div>
                ))}
              </div>

              <div className="flex justify-end gap-2 pt-3 border-t">
                <button
                  type="button"
                  onClick={() => { setShowAddPoModal(false); setPoAttachmentFile(null); }}
                  className="px-4 py-2 border rounded-xl text-xs font-bold hover:bg-muted"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={poSubmitBusy}
                  className="px-5 py-2 bg-violet-600 text-white font-bold rounded-xl text-xs hover:bg-violet-700 flex items-center gap-1.5"
                >
                  {poSubmitBusy ? <RefreshCw className="h-4 w-4 animate-spin" /> : <CheckCircle2 size={15} />}
                  Issue Purchase Order
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* View PO Details Modal */}
      {viewingPo && (() => {
        const poItems = Array.isArray(viewingPo.items) ? viewingPo.items : [];
        const totalOrdered = poItems.reduce((acc: number, it: any) => acc + (Number(it.quantity_ordered || 1) * Number(it.unit_price || 0)), 0) || Number(viewingPo.total_amount || viewingPo.total || 0);
        const totalReceived = poItems.reduce((acc: number, it: any) => acc + (Number(it.quantity_received || 0) * Number(it.unit_price || 0)), 0);
        const remaining = totalOrdered - totalReceived;
        const match = (viewingPo.notes || '').match(/\[Attached Docket:\s*([^\]]+)\]/i);
        const fileName = viewingPo.attachment_file_name || viewingPo.attachment || (match ? match[1] : null);

        return (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-xs overflow-y-auto">
            <div className="bg-card border rounded-2xl p-6 max-w-xl w-full space-y-4 shadow-2xl my-8">
              <div className="flex items-center justify-between border-b pb-3">
                <h3 className="font-bold text-base flex items-center gap-2">
                  <ShoppingBag className="h-5 w-5 text-violet-600" /> Purchase Order: {viewingPo.po_number || viewingPo.id}
                </h3>
                <button onClick={() => setViewingPo(null)} className="p-1 rounded-lg hover:bg-muted text-muted-foreground"><X size={18} /></button>
              </div>

              {/* Metadata Banner */}
              <div className="p-4 bg-muted/40 rounded-xl space-y-2 text-xs border">
                <div className="grid grid-cols-2 gap-2">
                  <p><strong>Vendor / Supplier:</strong> {viewingPo.supplier_name || viewingPo.vendor_name || viewingPo.vendor || viewingPo.supplier || 'Site Vendor'}</p>
                  <p><strong>Status:</strong> <StatusBadge status={viewingPo.status || 'PENDING'} /></p>
                  <p><strong>Project Assignment:</strong> {projects.find((p) => String(p.id) === String(viewingPo.project_id))?.name || viewingPo.project_id || 'Organization-Wide'}</p>
                  <p><strong>Order Date:</strong> {viewingPo.created_at ? new Date(viewingPo.created_at).toLocaleString() : '—'}</p>
                </div>
                {(viewingPo.notes || '').replace(/\[Attached Docket:\s*([^\]]+)\]/gi, '').trim() && (
                  <p className="pt-1 border-t border-border/50 text-muted-foreground">
                    <strong>Notes:</strong> {(viewingPo.notes || '').replace(/\[Attached Docket:\s*([^\]]+)\]/gi, '').trim()}
                  </p>
                )}
              </div>

              {/* Line Items Table */}
              <div className="space-y-2">
                <h4 className="font-bold text-xs uppercase tracking-wider text-muted-foreground">Order Line Items Breakdown</h4>
                <div className="border rounded-xl overflow-hidden text-xs">
                  <table className="w-full">
                    <thead className="bg-muted/60 border-b font-bold text-muted-foreground">
                      <tr>
                        <th className="p-2.5 text-left">Description</th>
                        <th className="p-2.5 text-center">Ordered</th>
                        <th className="p-2.5 text-center">Received</th>
                        <th className="p-2.5 text-right">Unit Price</th>
                        <th className="p-2.5 text-right">Line Total</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y">
                      {poItems.map((it: any, idx: number) => {
                        const qtyOrd = Number(it.quantity_ordered) || 1;
                        const qtyRec = Number(it.quantity_received) || 0;
                        const price = Number(it.unit_price) || 0;
                        return (
                          <tr key={idx} className="hover:bg-muted/30">
                            <td className="p-2.5 font-medium">{it.description || 'Line Item'}</td>
                            <td className="p-2.5 font-mono text-center">{qtyOrd}</td>
                            <td className="p-2.5 font-mono text-center text-emerald-600 font-bold">{qtyRec}</td>
                            <td className="p-2.5 font-mono text-right">${price.toLocaleString()}</td>
                            <td className="p-2.5 font-mono text-right font-bold text-foreground">${(qtyOrd * price).toLocaleString()}</td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </div>

              {/* Financial Summary Breakdown */}
              <div className="grid grid-cols-3 gap-2 p-3 bg-violet-50/50 dark:bg-violet-950/30 rounded-xl border border-violet-100 dark:border-violet-900 text-xs">
                <div>
                  <span className="text-[10px] text-muted-foreground font-bold uppercase block">Total Ordered</span>
                  <p className="font-black text-foreground">${totalOrdered.toLocaleString()}</p>
                </div>
                <div>
                  <span className="text-[10px] text-muted-foreground font-bold uppercase block">Goods Received</span>
                  <p className="font-black text-emerald-600">${totalReceived.toLocaleString()}</p>
                </div>
                <div>
                  <span className="text-[10px] text-muted-foreground font-bold uppercase block">Remaining Open</span>
                  <p className="font-black text-amber-600">${remaining > 0 ? remaining.toLocaleString() : '0'}</p>
                </div>
              </div>

              {/* Actions Footer */}
              <div className="flex flex-wrap items-center justify-between gap-2 pt-3 border-t">
                <button
                  type="button"
                  onClick={() => void handleDownloadPoFile(viewingPo)}
                  className="px-4 py-2 bg-violet-600 text-white font-bold rounded-xl text-xs hover:bg-violet-700 flex items-center gap-1.5 shadow-xs"
                >
                  <Download size={14} /> View / Download PO Attachment Docket {fileName ? `(${fileName})` : ''}
                </button>
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={() => { const targetPo = viewingPo; setViewingPo(null); openEditPoModal(targetPo); }}
                    className="px-3.5 py-2 border rounded-xl text-xs font-bold hover:bg-muted flex items-center gap-1"
                  >
                    <Pencil size={13} /> Edit PO
                  </button>
                  <button
                    type="button"
                    onClick={() => setViewingPo(null)}
                    className="px-4 py-2 bg-slate-900 dark:bg-slate-100 text-slate-100 dark:text-slate-900 font-bold rounded-xl text-xs hover:opacity-90"
                  >
                    Close
                  </button>
                </div>
              </div>
            </div>
          </div>
        );
      })()}

      {/* Edit Purchase Order Modal */}
      {editingPo && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-xs overflow-y-auto">
          <div className="bg-card border rounded-2xl p-6 max-w-xl w-full space-y-4 shadow-2xl my-8">
            <div className="flex items-center justify-between border-b pb-3 border-border">
              <h3 className="font-bold text-base flex items-center gap-2 text-foreground">
                <Pencil className="h-5 w-5 text-violet-600" /> Edit Purchase Order: {editingPo.po_number || editingPo.id}
              </h3>
              <button onClick={() => setEditingPo(null)} className="p-1 rounded-lg hover:bg-muted text-muted-foreground"><X size={18} /></button>
            </div>

            <form onSubmit={handleUpdatePo} className="space-y-4">
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-bold text-foreground mb-1">Vendor / Supplier Name *</label>
                  <input
                    type="text"
                    required
                    placeholder="Vendor / Supplier Name"
                    value={editPoForm.supplier_name}
                    onChange={(e) => setEditPoForm({ ...editPoForm, supplier_name: e.target.value })}
                    className="w-full p-2.5 border rounded-xl bg-background text-xs"
                  />
                </div>
                <div>
                  <label className="block text-xs font-bold text-foreground mb-1">Project Assignment</label>
                  <select
                    value={editPoForm.project_id}
                    onChange={(e) => setEditPoForm({ ...editPoForm, project_id: e.target.value })}
                    className="w-full p-2.5 border rounded-xl bg-background text-xs"
                  >
                    <option value="">Organization-Wide (All Projects)</option>
                    {projects.map((p) => (
                      <option key={p.id} value={p.id}>{p.name}</option>
                    ))}
                  </select>
                </div>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-bold text-foreground mb-1">Status</label>
                  <select
                    value={editPoForm.status}
                    onChange={(e) => setEditPoForm({ ...editPoForm, status: e.target.value })}
                    className="w-full p-2.5 border rounded-xl bg-background text-xs font-bold"
                  >
                    <option value="DRAFT">DRAFT</option>
                    <option value="PENDING">PENDING</option>
                    <option value="APPROVED">APPROVED</option>
                    <option value="COMPLETED">COMPLETED</option>
                    <option value="CANCELLED">CANCELLED</option>
                  </select>
                </div>
                <div>
                  <label className="block text-xs font-bold text-foreground mb-1">Currency</label>
                  <select
                    value={editPoForm.currency}
                    onChange={(e) => setEditPoForm({ ...editPoForm, currency: e.target.value })}
                    className="w-full p-2.5 border rounded-xl bg-background text-xs font-bold"
                  >
                    <option value="USD">USD ($)</option>
                    <option value="EUR">EUR (€)</option>
                    <option value="GBP">GBP (£)</option>
                    <option value="ZAR">ZAR (R)</option>
                  </select>
                </div>
              </div>

              <div>
                <label className="block text-xs font-bold text-foreground mb-1">Attachment Docket File</label>
                {editPoForm.existingAttachment && !editPoAttachmentFile && (
                  <p className="text-[11px] text-muted-foreground mb-1.5 flex items-center gap-1">
                    <Paperclip size={12} className="text-violet-600" /> Current attached file: <strong>{editPoForm.existingAttachment}</strong>
                  </p>
                )}
                <input
                  type="file"
                  onChange={(e) => setEditPoAttachmentFile(e.target.files?.[0] || null)}
                  className="w-full p-2 border rounded-xl bg-background text-xs text-muted-foreground file:mr-3 file:py-1 file:px-2.5 file:rounded-lg file:border-0 file:text-xs file:font-bold file:bg-violet-50 file:text-violet-700 hover:file:bg-violet-100"
                />
              </div>

              <div>
                <label className="block text-xs font-bold text-foreground mb-1">Operational Notes</label>
                <input
                  type="text"
                  placeholder="Purchase Order Notes / Specifications"
                  value={editPoForm.notes}
                  onChange={(e) => setEditPoForm({ ...editPoForm, notes: e.target.value })}
                  className="w-full p-2.5 border rounded-xl bg-background text-xs"
                />
              </div>

              {/* Line Items List */}
              <div className="space-y-2 border-t pt-3">
                <div className="flex items-center justify-between">
                  <label className="text-xs font-bold text-foreground uppercase tracking-wider">Purchase Order Line Items</label>
                  <button
                    type="button"
                    onClick={() => setEditPoForm({
                      ...editPoForm,
                      items: [...editPoForm.items, { description: '', quantity_ordered: 1, unit_price: 0 }],
                    })}
                    className="text-xs font-bold text-violet-600 hover:underline flex items-center gap-1"
                  >
                    <Plus size={13} /> Add Item
                  </button>
                </div>

                {editPoForm.items.map((it, idx) => (
                  <div key={idx} className="flex items-center gap-2 p-2 border rounded-xl bg-muted/40">
                    <input
                      type="text"
                      placeholder="Item Description"
                      value={it.description}
                      onChange={(e) => {
                        const updated = [...editPoForm.items];
                        updated[idx].description = e.target.value;
                        setEditPoForm({ ...editPoForm, items: updated });
                      }}
                      className="flex-1 p-1.5 border rounded-lg bg-background text-xs"
                    />
                    <input
                      type="number"
                      placeholder="Qty"
                      min="1"
                      value={it.quantity_ordered}
                      onChange={(e) => {
                        const updated = [...editPoForm.items];
                        updated[idx].quantity_ordered = Number(e.target.value) || 1;
                        setEditPoForm({ ...editPoForm, items: updated });
                      }}
                      className="w-16 p-1.5 border rounded-lg bg-background text-xs font-mono text-center"
                    />
                    <input
                      type="number"
                      placeholder="Price"
                      min="0"
                      value={it.unit_price}
                      onChange={(e) => {
                        const updated = [...editPoForm.items];
                        updated[idx].unit_price = Number(e.target.value) || 0;
                        setEditPoForm({ ...editPoForm, items: updated });
                      }}
                      className="w-20 p-1.5 border rounded-lg bg-background text-xs font-mono text-right"
                    />
                    {editPoForm.items.length > 1 && (
                      <button
                        type="button"
                        onClick={() => {
                          const updated = editPoForm.items.filter((_, i) => i !== idx);
                          setEditPoForm({ ...editPoForm, items: updated });
                        }}
                        className="p-1 text-red-500 hover:text-red-700"
                      >
                        <Trash2 size={14} />
                      </button>
                    )}
                  </div>
                ))}
              </div>

              <div className="flex justify-end gap-2 pt-3 border-t">
                <button
                  type="button"
                  onClick={() => setEditingPo(null)}
                  className="px-4 py-2 border rounded-xl text-xs font-bold hover:bg-muted"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={poSubmitBusy}
                  className="px-5 py-2 bg-violet-600 text-white font-bold rounded-xl text-xs hover:bg-violet-700 flex items-center gap-1.5"
                >
                  {poSubmitBusy ? <RefreshCw className="h-4 w-4 animate-spin" /> : <CheckCircle2 size={15} />}
                  Save Changes
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Goods Receipt (GRN) Modal */}
      {receivingPo && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-xs">
          <div className="bg-card border rounded-2xl p-6 max-w-lg w-full space-y-4 shadow-2xl">
            <div className="flex items-center justify-between border-b pb-3">
              <h3 className="font-bold text-base flex items-center gap-2">
                <PackageCheck className="h-5 w-5 text-emerald-600" /> Receive Goods (GRN): {receivingPo.po_number || receivingPo.id}
              </h3>
              <button onClick={() => setReceivingPo(null)} className="p-1 rounded-lg hover:bg-muted text-muted-foreground"><X size={18} /></button>
            </div>

            <form onSubmit={handleReceiveGoods} className="space-y-4">
              <p className="text-xs text-muted-foreground">
                Enter quantity received into inventory for each line item below:
              </p>

              <div className="border rounded-xl overflow-hidden text-xs">
                <table className="w-full">
                  <thead className="bg-muted/60 border-b">
                    <tr>
                      <th className="p-2 text-left">Line Item</th>
                      <th className="p-2 text-center">Ordered</th>
                      <th className="p-2 text-center">Receive Now</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y">
                    {(receivingPo.items || [{ id: '1', description: 'Operational Supplies', quantity_ordered: 5 }]).map((it: any, idx: number) => {
                      const itemId = it.id || it.description || String(idx);
                      return (
                        <tr key={itemId}>
                          <td className="p-2 font-medium">{it.description}</td>
                          <td className="p-2 font-mono text-center">{it.quantity_ordered}</td>
                          <td className="p-2 text-center">
                            <input
                              type="number"
                              min="0"
                              max={it.quantity_ordered}
                              value={receiptQuantities[itemId] ?? (it.quantity_ordered - (it.quantity_received || 0))}
                              onChange={(e) => setReceiptQuantities({ ...receiptQuantities, [itemId]: Number(e.target.value) || 0 })}
                              className="w-16 p-1 border rounded bg-background text-center font-mono"
                            />
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>

              <div className="flex justify-end gap-2 pt-2 border-t">
                <button
                  type="button"
                  onClick={() => setReceivingPo(null)}
                  className="px-4 py-2 border rounded-xl text-xs font-bold hover:bg-muted"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={poSubmitBusy}
                  className="px-4 py-2 bg-emerald-600 text-white font-bold rounded-xl text-xs hover:bg-emerald-700 flex items-center gap-1.5"
                >
                  {poSubmitBusy ? <RefreshCw className="h-4 w-4 animate-spin" /> : <PackageCheck size={15} />}
                  Confirm Goods Receipt Note
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Fuel Receipt View Modal */}
      {viewingReceiptDelivery && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-xs">
          <div className="bg-card border rounded-2xl p-6 max-w-lg w-full space-y-4 shadow-2xl">
            <div className="flex items-center justify-between border-b pb-3">
              <h3 className="font-bold text-base flex items-center gap-2">
                <Paperclip className="h-5 w-5 text-violet-600" /> Fuel Receipt Docket
              </h3>
              <button onClick={() => setViewingReceiptDelivery(null)} className="p-1 rounded-lg hover:bg-muted text-muted-foreground"><X size={18} /></button>
            </div>
            <div className="p-4 bg-muted/40 rounded-xl space-y-2 text-xs font-mono">
              <p><strong>Ref #:</strong> {viewingReceiptDelivery.reference_number || viewingReceiptDelivery.id}</p>
              <p><strong>Supplier:</strong> {viewingReceiptDelivery.supplier || 'Site Bulk Supply'}</p>
              <p><strong>Litres:</strong> {viewingReceiptDelivery.quantity_litres} L</p>
              <p><strong>Total Cost:</strong> ${fuelDeliveryCost(viewingReceiptDelivery).toLocaleString()}</p>
            </div>
            <div className="flex justify-end gap-2 pt-2">
              <button
                type="button"
                onClick={() => handleDownloadFuelReceipt(viewingReceiptDelivery)}
                className="px-4 py-2 bg-violet-600 text-white font-bold rounded-xl text-xs hover:bg-violet-700 flex items-center gap-1.5"
              >
                <Download size={14} /> Download Receipt Docket
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Expense Claim View Docket Modal */}
      {viewingExpense && (() => {
        const vName = viewingExpense.submitted_by_name || viewingExpense.submitted_by?.full_name || (viewingExpense.submitted_by?.first_name ? `${viewingExpense.submitted_by.first_name} ${viewingExpense.submitted_by.last_name || ''}`.trim() : null) || viewingExpense.created_by_name || (user?.first_name ? `${user.first_name} ${user.last_name || ''}`.trim() : 'Operations Supervisor');
        const vPos = viewingExpense.submitted_by_position || viewingExpense.submitted_by_title || viewingExpense.submitted_by?.job_title || viewingExpense.submitted_by?.role || (user?.is_superuser ? 'Operations Director' : user?.portal_type ? `${user.portal_type.replace('_', ' ')} Admin` : 'Field Administrator');
        const vEmail = viewingExpense.submitted_by_email || viewingExpense.submitted_by?.email || viewingExpense.email || user?.email || 'operations@cestos.com';

        return (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-xs">
            <div className="bg-card border rounded-2xl p-6 max-w-lg w-full space-y-4 shadow-2xl">
              <div className="flex items-center justify-between border-b pb-3 border-border">
                <h3 className="font-bold text-base flex items-center gap-2 text-foreground">
                  <Paperclip className="h-5 w-5 text-violet-600" /> Operational Expense Claim Docket
                </h3>
                <button onClick={() => setViewingExpense(null)} className="p-1 rounded-lg hover:bg-muted text-muted-foreground"><X size={18} /></button>
              </div>
              <div className="p-4 bg-muted/40 rounded-xl space-y-2 text-xs font-mono border">
                <p><strong>Voucher Ref #:</strong> {viewingExpense.expense_number || viewingExpense.reference_number || viewingExpense.id}</p>
                <div className="border-y border-border/50 py-1.5 my-1 font-sans">
                  <p className="text-[11px] text-muted-foreground font-bold uppercase tracking-wider mb-0.5">Submitted By Details</p>
                  <p className="font-bold text-foreground flex items-center gap-1"><User size={12} className="text-violet-600" /> {vName}</p>
                  <p className="text-[11px] text-muted-foreground font-medium">{vPos}</p>
                  <a href={`mailto:${vEmail}`} className="text-violet-600 dark:text-violet-400 hover:underline font-mono text-[11px] font-bold inline-flex items-center gap-1 mt-0.5">
                    <Mail size={11} /> {vEmail}
                  </a>
                </div>
                <p><strong>Payee Name:</strong> {viewingExpense.pay_to_name}</p>
                <p><strong>Payment Method:</strong> {viewingExpense.payment_method || 'MOBILE_MONEY'}</p>
                <p><strong>Total Cost:</strong> ${Number(viewingExpense.total_cost || viewingExpense.amount || 0).toLocaleString()}</p>
                <p><strong>Status:</strong> <StatusBadge status={viewingExpense.status || 'SUBMITTED'} /></p>
              </div>
              <div className="flex flex-wrap justify-end gap-2 pt-2 border-t border-border">
                <button
                  type="button"
                  onClick={() => void handleOpenFile(`/api/v1/operational-expenses/${viewingExpense.id}/files/invoice`, viewingExpense.invoice_name || 'Invoice')}
                  className="px-3.5 py-2 bg-violet-600 text-white font-bold rounded-xl text-xs hover:bg-violet-700 flex items-center gap-1.5 shadow-xs"
                >
                  <Download size={14} /> View / Download Invoice Docket
                </button>
                {viewingExpense.receipt_name && (
                  <button
                    type="button"
                    onClick={() => void handleOpenFile(`/api/v1/operational-expenses/${viewingExpense.id}/files/receipt`, viewingExpense.receipt_name || 'Receipt')}
                    className="px-3.5 py-2 bg-emerald-600 text-white font-bold rounded-xl text-xs hover:bg-emerald-700 flex items-center gap-1.5 shadow-xs"
                  >
                    <Download size={14} /> Download Payment Receipt
                  </button>
                )}
              </div>
            </div>
          </div>
        );
      })()}

      {/* Floating Bubble Widget for Unresolved Claims */}
      {unresolvedClaimsCount > 0 && activeTab !== 'OPERATIONAL_EXPENSES' && (
        <button
          type="button"
          onClick={() => setActiveTab('OPERATIONAL_EXPENSES')}
          className="fixed bottom-6 right-6 z-50 flex items-center gap-2.5 px-4 py-3 bg-violet-600 hover:bg-violet-700 text-white rounded-full shadow-2xl transition-all duration-300 transform hover:scale-105 border-2 border-white/20 active:scale-95 group"
          title="Click to review unresolved expense claims"
        >
          <div className="relative">
            <FileText size={18} />
            <span className="absolute -top-1.5 -right-1.5 w-4 h-4 bg-amber-400 text-slate-950 text-[9px] font-black rounded-full flex items-center justify-center border border-white">
              {unresolvedClaimsCount}
            </span>
          </div>
          <div className="text-left font-sans">
            <p className="text-xs font-black leading-none">{unresolvedClaimsCount} Unresolved Claims</p>
            <p className="text-[10px] text-violet-200 font-medium leading-tight group-hover:underline">Click to open &amp; review</p>
          </div>
          <ChevronRight size={14} className="text-violet-200 group-hover:translate-x-0.5 transition-transform" />
        </button>
      )}
    </div>
