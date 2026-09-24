const expenseTimeSeriesData = React.useMemo(() => {
    const dateMap: Record<string, { date: string; fullDate: string; totalCost: number; approvedCost: number }> = {};

    expenses.forEach((e: any) => {
      const dateStr = e.expense_date ? new Date(e.expense_date).toISOString().slice(0, 10) : e.created_at?.slice(0, 10) || 'Unknown';
      if (dateStr === 'Unknown') return;
      if (!dateMap[dateStr]) {
        const dObj = new Date(dateStr);
        const formattedDate = isNaN(dObj.getTime()) ? dateStr : dObj.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
        dateMap[dateStr] = { date: formattedDate, fullDate: dateStr, totalCost: 0, approvedCost: 0 };
      }
      const cost = Number(e.total_cost || e.amount || 0);
      dateMap[dateStr].totalCost += cost;
      const s = (e.status || '').toUpperCase();
      if (s === 'APPROVED' || s === 'COMPLETED') {
        dateMap[dateStr].approvedCost += cost;
      }
    });

    return Object.values(dateMap).sort((a, b) => a.fullDate.localeCompare(b.fullDate));
  }, [expenses]);

  const topItemsByCostData = React.useMemo(() => {
    const itemMap: Record<string, { name: string; totalCost: number; count: number }> = {};

    expenses.forEach((e: any) => {
      const items = Array.isArray(e.items) ? e.items : [];
      if (items.length > 0) {
        items.forEach((item: any) => {
          const name = (item.name || item.item_name || 'General Item').trim();
          if (!itemMap[name]) itemMap[name] = { name, totalCost: 0, count: 0 };
          const qty = Number(item.quantity) || 1;
          const unitC = Number(item.unit_cost) || 0;
          const cost = item.total ? Number(item.total) : qty * unitC;
          itemMap[name].totalCost += cost > 0 ? cost : Number(e.total_cost || 0) / items.length;
          itemMap[name].count += 1;
        });
      } else {
        const name = (e.pay_to_name || 'Operational Expense').trim();
        if (!itemMap[name]) itemMap[name] = { name, totalCost: 0, count: 0 };
        itemMap[name].totalCost += Number(e.total_cost || e.amount || 0);
        itemMap[name].count += 1;
      }
    });

    [].forEach((c: any) => {
      const name = (c.description || c.cost_category || 'Subledger Expense').trim();
      if (!itemMap[name]) itemMap[name] = { name, totalCost: 0, count: 0 };
      itemMap[name].totalCost += Number(c.amount || 0);
      itemMap[name].count += 1;
    });

    return Object.values(itemMap).sort((a, b) => b.totalCost - a.totalCost).slice(0, 6);
  }, [expenses, []]);

  const topItemsByFrequencyData = React.useMemo(() => {
    const itemMap: Record<string, { name: string; frequency: number; totalCost: number }> = {};

    expenses.forEach((e: any) => {
      const items = Array.isArray(e.items) ? e.items : [];
      if (items.length > 0) {
        items.forEach((item: any) => {
          const name = (item.name || item.item_name || 'General Item').trim();
          if (!itemMap[name]) itemMap[name] = { name, frequency: 0, totalCost: 0 };
          const qty = Number(item.quantity) || 1;
          const unitC = Number(item.unit_cost) || 0;
          const cost = item.total ? Number(item.total) : qty * unitC;
          itemMap[name].frequency += 1;
          itemMap[name].totalCost += cost > 0 ? cost : Number(e.total_cost || 0) / items.length;
        });
      } else {
        const name = (e.pay_to_name || 'Operational Expense').trim();
        if (!itemMap[name]) itemMap[name] = { name, frequency: 0, totalCost: 0 };
        itemMap[name].frequency += 1;
        itemMap[name].totalCost += Number(e.total_cost || e.amount || 0);
      }
    });

    return Object.values(itemMap).sort((a, b) => b.frequency - a.frequency).slice(0, 6);
  }, [expenses]);

  const topVendorData = React.useMemo(() => {
    const vendorMap: Record<string, { vendor: string; totalCost: number; count: number }> = {};

    expenses.forEach((e: any) => {
      const vendor = (e.pay_to_name || 'Unspecified Payee').trim();
      if (!vendorMap[vendor]) vendorMap[vendor] = { vendor, totalCost: 0, count: 0 };
      vendorMap[vendor].totalCost += Number(e.total_cost || e.amount || 0);
      vendorMap[vendor].count += 1;
    });

    return Object.values(vendorMap).sort((a, b) => b.totalCost - a.totalCost).slice(0, 6);
  }, [expenses]);

  const expenseIntelligenceMetrics = React.useMemo(() => {
    const totalExp = expenses.reduce((sum, e) => sum + Number(e.total_cost || e.amount || 0), 0);
    const count = expenses.length;
    const avgClaim = count > 0 ? totalExp / count : 0;
    const maxClaim = expenses.reduce((max, e) => Math.max(max, Number(e.total_cost || e.amount || 0)), 0);
    const totalItemsCount = expenses.reduce((sum, e) => sum + (Array.isArray(e.items) ? e.items.length : 1), 0);

    return { totalExp, count, avgClaim, maxClaim, totalItemsCount };
  }, [expenses]);