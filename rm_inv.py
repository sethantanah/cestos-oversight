with open('c:/Users/User/Documents/Projects/cestos-apps/cestos/src/components/ExecutivePortalWorkspace.tsx', 'r', encoding='utf-8') as f:
    lines = f.readlines()

del lines[874:919]
with open('c:/Users/User/Documents/Projects/cestos-apps/cestos/src/components/ExecutivePortalWorkspace.tsx', 'w', encoding='utf-8') as f:
    f.writelines(lines)
