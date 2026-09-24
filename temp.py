with open('c:/Users/User/Documents/Projects/cestos-apps/cestos/src/components/FinancePortalWorkspace.tsx', 'r', encoding='utf-8') as f:
    lines = f.readlines()
start = -1
end = -1
for i, line in enumerate(lines):
    if "case 'EXPENSES': {" in line:
        start = i
    if start != -1 and "case 'OPERATIONAL_EXPENSES':" in line:
        end = i
        break
with open('temp_render.tsx', 'w', encoding='utf-8') as f:
    f.writelines(lines[start:end-1])
