// Source-DOM probe linked to the actual KOReader CRengine. No UI or database writes.
#include "lvtinydom.h"
#include "lvfntman.h"
#include "epubfmt.h"
#include "fb2def.h"
#define XS_IMPLEMENT_SCHEME
#include "fb2def.h"
#include <iostream>
#include <string>

static std::string json(const std::string &s) {
    std::string out = "\"";
    const char *hex = "0123456789abcdef";
    for (unsigned char c : s) {
        if (c == '"' || c == '\\') { out += '\\'; out += c; }
        else if (c < 32) { out += "\\u00"; out += hex[c >> 4]; out += hex[c & 15]; }
        else out += c;
    }
    return out + '"';
}
static std::string utf8(const lString32 &s) { return UnicodeToUtf8(s).c_str(); }

int main(int argc, char **argv) {
    if (argc < 3) { std::cerr << "usage: crengine-probe book.epub xpointer...\n"; return 2; }
    InitFontManager(lString8());
    ldomDocument doc;
    doc.setNodeTypes(fb2_elem_table);
    doc.setAttributeTypes(fb2_attr_table);
    doc.setNameSpaceTypes(fb2_ns_table);
    doc.setDOMVersionRequested(gDOMVersionCurrent);
    doc.setDocFlags(DOC_FLAG_DEFAULTS);
    LVStreamRef stream = LVOpenFileStream(argv[1], LVOM_READ);
    if (stream.isNull() || !ImportEpubDocument(stream, &doc, NULL, NULL)) {
        std::cerr << "Cannot import EPUB\n"; return 3;
    }
    std::cout << "{\"dom_version\":" << gDOMVersionCurrent << ",\"rendered\":false,\"results\":[";
    for (int i=2; i<argc; ++i) {
        if (i>2) std::cout << ',';
        std::cout << "{\"requested_xpointer\":" << json(argv[i]);
        auto point = doc.createXPointer(Utf8ToUnicode(argv[i]));
        if (point.isNull()) { std::cout << ",\"resolved\":false}"; continue; }
        auto node = point.getNode();
        auto text = node->getText();
        bool valid = !node->isText() || (point.getOffset() >= 0 && point.getOffset() <= text.length());
        std::cout << ",\"resolved\":" << (valid ? "true" : "false")
                  << ",\"canonical\":" << json(utf8(point.toString()))
                  << ",\"cfi\":" << json(utf8(ldomEPubCFI(point).toString()))
                  << ",\"is_text\":" << (node->isText() ? "true" : "false")
                  << ",\"offset_codepoints\":" << point.getOffset()
                  << ",\"node_text\":" << json(utf8(text)) << '}';
    }
    std::cout << "]}\n";
    return 0;
}
