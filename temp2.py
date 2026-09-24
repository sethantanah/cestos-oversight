import re
with open('c:/Users/User/Documents/Projects/cestos-apps/cestos/src/components/FinancePortalWorkspace.tsx', 'r', encoding='utf-8') as f:
    content = f.read()

hooks_match = re.search(r'(const expenseTimeSeriesData = React\.useMemo.*?const expenseIntelligenceMetrics = React\.useMemo.*?\}, \[scopedOperationalExpenseRequests\]\);)', content, re.DOTALL)
if hooks_match:
    hooks_block = hooks_match.group(1)
    hooks_block = hooks_block.replace('scopedOperationalExpenseRequests', 'expenses')
    hooks_block = hooks_block.replace('scopedExpenses', '[]')
    hooks_block = hooks_block.replace('operationalExpenseRequests', 'expenses')
    with open('temp_hooks.tsx', 'w', encoding='utf-8') as f:
        f.write(hooks_block)
else:
    print('Hooks block not found')
