#!/usr/bin/env python3
"""Idempotently apply the NV exporter to the pinned BiteDJ checkout."""
from pathlib import Path
import shutil
import subprocess

root = Path(__file__).resolve().parents[1]
source = root / 'vendor/bitedj'
pin = '78074e05c8bf99ede6fedd755aa68bd222ba343c'
head = subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD']).decode().strip()
if head != pin:
    raise SystemExit('Unexpected BiteDJ revision; review before applying integration.')
for name in ('numarknvexporter.h', 'numarknvexporter.cpp'):
    shutil.copy2(root / 'native' / name, source / 'src/controllers' / name)
# Move the old hook after effects setup and library construction on upgrades.
core = source / 'src/coreservices.cpp'
core.write_text(core.read_text().replace('\n    new NumarkNvExporter(m_pPlayerManager.get());', ''))
edits = [
    ('CMakeLists.txt', '  src/mixer/basetrackplayer.cpp',
     '  src/controllers/numarknvexporter.cpp\n  src/mixer/basetrackplayer.cpp'),
    ('src/coreservices.cpp', '#include "coreservices.h"',
     '#include "coreservices.h"\n#include "controllers/numarknvexporter.h"'),
    ('src/coreservices.cpp', '    m_pPlayerManager->bindToLibrary(m_pLibrary.get());',
     '    m_pPlayerManager->bindToLibrary(m_pLibrary.get());\n'
     '    new NumarkNvExporter(m_pPlayerManager.get(), m_pEffectsManager.get(), m_pLibrary.get());'),
    ('src/library/library.h', '    void bindSearchboxWidget(WSearchLineEdit* pSearchboxWidget);',
     '    // Read-only access for bounded NV telemetry; pointers clear on widget destruction.\n'
     '    WLibrary* nvLibraryWidget() const;\n'
     '    WLibrarySidebar* nvSidebarWidget() const;\n'
     '    void bindSearchboxWidget(WSearchLineEdit* pSearchboxWidget);'),
    ('src/library/library.h', '    WLibrary* m_pLibraryWidget;',
     '    WLibrary* m_pLibraryWidget;\n'
     '    QPointer<WLibrary> m_nvLibraryWidget;\n'
     '    QPointer<WLibrarySidebar> m_nvSidebarWidget;'),
    ('src/library/library.cpp', 'void Library::bindSidebarWidget(WLibrarySidebar* pSidebarWidget) {',
     'WLibrary* Library::nvLibraryWidget() const { return m_nvLibraryWidget.data(); }\n'
     'WLibrarySidebar* Library::nvSidebarWidget() const { return m_nvSidebarWidget.data(); }\n\n'
     'void Library::bindSidebarWidget(WLibrarySidebar* pSidebarWidget) {\n'
     '    m_nvSidebarWidget = pSidebarWidget;'),
    ('src/library/library.cpp', '    m_pLibraryWidget = pLibraryWidget;',
     '    m_pLibraryWidget = pLibraryWidget;\n    m_nvLibraryWidget = pLibraryWidget;'),
]
for name, old, new in edits:
    file = source / name
    text = file.read_text()
    if new in text:
        continue
    if text.count(old) != 1:
        raise SystemExit('Unexpected source context: ' + name)
    file.write_text(text.replace(old, new))
# Apply/recheck the exact pinned mixed-folder fix, never overwrite local edits.
patch = root / 'native/browser_navigation.patch'
check = subprocess.run(['git', '-C', str(source), 'apply', '--check', str(patch)],
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
if check.returncode == 0:
    subprocess.run(['git', '-C', str(source), 'apply', str(patch)], check=True)
else:
    subprocess.run(['git', '-C', str(source), 'apply', '--reverse', '--check', str(patch)], check=True)
print('Native NV exporter and mixed-folder fix applied to', pin)

