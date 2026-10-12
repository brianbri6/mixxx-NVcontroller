"""Exercise the patched C++ eligibility method, using minimal model test doubles.

This runs the actual method body, not a Python rewrite. It is not a Qt GUI test.
Run after scripts/apply_native.py; absent native sources explicitly skip it.
"""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


def function(source, signature):
    start = source.index(signature)
    opening = source.index('{', start)
    depth = 1
    end = opening + 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[start:end]


class NativeBrowserTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('g++'), 'requires host C++ compiler')
    def test_actual_directory_eligibility_method(self):
        source = ROOT/'vendor/bitedj/src/library/sidebarmodel.cpp'
        if not source.exists():
            self.skipTest('restore pinned native source and run scripts/apply_native.py')
        body = function(source.read_text(), 'bool SidebarModel::hasTrackTable(')
        code = r'''
#include <cassert>
#include <string>
#include <vector>
struct QString : std::string {
    using std::string::string;
    bool isEmpty() const { return empty(); }
};
struct Value { QString s; QString toString() const { return s; } };
struct LibraryFeature {
    bool table = false;
    virtual ~LibraryFeature() = default;
    bool hasTrackTable() const { return table; }
};
struct BrowseFeature : LibraryFeature {};
struct OtherFeature : LibraryFeature {};
struct TreeItem {
    LibraryFeature* owner; Value path;
    LibraryFeature* feature() const { return owner; }
    Value getData() const { return path; }
};
struct QModelIndex {
    bool valid; const void* owner; void* item; int rowNumber;
    bool isValid() const { return valid; }
    const void* model() const { return owner; }
    void* internalPointer() const { return item; }
    int row() const { return rowNumber; }
};
template<class T> T qobject_cast(LibraryFeature* feature) {
    return dynamic_cast<T>(feature);
}
#define QUICK_LINK_NODE "::mixxx_quick_lnk_node::"
#define DEVICE_NODE "::mixxx_device_node::"
struct SidebarModel {
    std::vector<LibraryFeature*> m_sFeatures;
    bool hasTrackTable(const QModelIndex&) const;
};
''' + body + r'''
int main() {
    SidebarModel m;
    BrowseFeature browse;
    OtherFeature other;
    m.m_sFeatures = {&browse, &other};
    assert(!m.hasTrackTable({false, nullptr, nullptr, 99}));
    assert(!m.hasTrackTable({true, nullptr, nullptr, 99}));
    assert(!m.hasTrackTable({true, &m, nullptr, 0}));
    assert(!m.hasTrackTable({true, &m, &m, 0}));
    other.table = true;
    assert(m.hasTrackTable({true, &m, &m, 1}));
    for (const char* path : {"/media/MUSIC/Folder 1/", "/media/MUSIC/Folder 1/Folder 2/",
                            "/media/MUSIC/empty/", "/media/MUSIC/parent with children/"}) {
        TreeItem item{&browse, {QString(path)}};
        assert(m.hasTrackTable({true, &m, &item, 0}));
    }
    for (const char* path : {"", QUICK_LINK_NODE, DEVICE_NODE}) {
        TreeItem item{&browse, {QString(path)}};
        assert(!m.hasTrackTable({true, &m, &item, 0}));
    }
    TreeItem unrelated{&other, {QString("/not-a-browse-node/")}};
    assert(!m.hasTrackTable({true, &m, &unrelated, 0}));
    TreeItem noFeature{nullptr, {QString("/orphan/")}};
    assert(!m.hasTrackTable({true, &m, &noFeature, 0}));
}
'''
        with tempfile.TemporaryDirectory() as tmp:
            cpp = Path(tmp)/'test.cpp'; binary = Path(tmp)/'test'
            cpp.write_text(code)
            subprocess.run(['g++', '-std=c++17', '-Wall', '-Wextra', '-Werror', str(cpp), '-o', str(binary)], check=True)
            subprocess.run([str(binary)], check=True)

    def test_mouse_and_controller_use_eligibility_without_removing_expansion(self):
        source = ROOT/'vendor/bitedj/src/widget/wlibrarysidebar.cpp'
        if not source.exists():
            self.skipTest('restore pinned native source and run scripts/apply_native.py')
        s = source.read_text()
        mouse = function(s, 'void WLibrarySidebar::mousePressEvent(')
        enter = function(s, 'void WLibrarySidebar::activateSelectedLeaf(')
        expand = function(s, 'void WLibrarySidebar::toggleSelectedItem(')
        self.assertIn('sidebarModel->hasTrackTable(idx)', mouse)
        self.assertIn('visualRect(idx).contains(event->pos())', mouse)
        self.assertIn('!isLeafNodeSelected()', enter)
        for method in (mouse, enter):
            self.assertLess(method.index('emit clicked(idx)'), method.index('emit leafItemActivated'))
        self.assertIn('setExpanded(index, !isExpanded(index))', expand)


if __name__ == '__main__':
    unittest.main()
