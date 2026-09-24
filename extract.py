import re
with open('c:/Users/User/Documents/Projects/cestos-apps/cestos/src/components/FinancePortalWorkspace.tsx', 'r', encoding='utf-8') as f:
    fin = f.read()
match_jsx = re.search(r'(<!-- 1\. Operational Expenditure.*?)(?=</main>)', fin, re.DOTALL)
if match_jsx:
    with open('jsx.txt', 'w', encoding='utf-8') as f: f.write(match_jsx.group(1))
