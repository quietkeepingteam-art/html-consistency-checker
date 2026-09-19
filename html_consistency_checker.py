#!/usr/bin/env python3
"""
HTML Consistency Checker
- Pick a folder of .html files and a MODEL (reference) file.
- Check: compares every page against the model (fonts, head tags, stylesheets,
  header/nav/footer, colors, headings).
- Fix: backs up every file it will change, then repairs what it safely can.
- Restore: puts back the files from the most recent backup.
Uses only the Python standard library (tkinter ships with Python).
"""
import os
import re
import shutil
import datetime
from collections import Counter

try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, scrolledtext
except ImportError:  # lets the core logic be imported/tested without a display
    tk = None

BACKUP_DIR = "_backups"
BLOCK_TAGS = ("header", "nav", "footer")
FONT_RE = re.compile(r"font-family\s*:\s*([^;}{]+)", re.I)


# ---------- file helpers ----------
def read(path):
    with open(path, encoding="utf-8", newline="") as f:
        return f.read()


def write(path, text):
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text)


def find_html(folder, recursive):
    found = []
    for root, dirs, files in os.walk(folder):
        dirs[:] = [d for d in dirs if d != BACKUP_DIR and not d.startswith(".")]
        for name in files:
            if name.lower().endswith((".html", ".htm")):
                found.append(os.path.join(root, name))
        if not recursive:
            break
    return sorted(found)


# ---------- parsing helpers ----------
def attr(tag, name):
    m = re.search(r'\b%s\s*=\s*["\']([^"\']*)["\']' % name, tag, re.I)
    return m.group(1) if m else None


def get_block(html, tag):
    return re.search(r"<%s\b[^>]*>.*?</%s>" % (tag, tag), html, re.S | re.I)


def norm_ws(s):
    return re.sub(r"\s+", " ", s).strip()


def signature(block, strict):
    if strict:
        return norm_ws(block)
    tags = tuple(re.findall(r"<\s*([a-zA-Z0-9]+)", block))
    hrefs = tuple(sorted(set(re.findall(r'href\s*=\s*["\']([^"\']*)', block))))
    return (tags, hrefs)


def split_val(raw):
    val = raw
    if val.count('"') % 2 == 1:  # value ran past an inline style="..." quote
        val = val[: val.rfind('"')]
    val = re.sub(r"\s*!important\s*$", "", val, flags=re.I)
    val = val.rstrip()
    return val, raw[len(val):]


def norm_font(val):
    v = val.lower().replace("&quot;", "").replace('"', "").replace("'", "")
    v = re.sub(r"\s*,\s*", ",", v)
    return norm_ws(v)


def skip_font(n):
    return (not n or n.startswith(("var(", "inherit", "initial", "unset"))
            or "monospace" in n)


def analyze(html):
    p = {}
    m = re.search(r"<html\b[^>]*\blang\s*=\s*[\"']([^\"']+)", html, re.I)
    p["lang"] = m.group(1) if m else None
    m = re.search(r"<meta\b[^>]*charset[^>]*>", html, re.I)
    p["charset"] = m.group(0) if m else None
    m = re.search(r"<meta\b[^>]*name\s*=\s*[\"']viewport[^>]*>", html, re.I)
    p["viewport"] = m.group(0) if m else None
    p["title"] = bool(re.search(r"<title\b[^>]*>\s*\S", html, re.I))
    links = {}
    for m in re.finditer(r"<link\b[^>]*>", html, re.I):
        tag = m.group(0)
        rel, href = attr(tag, "rel"), attr(tag, "href")
        if rel and href and ("stylesheet" in rel.lower() or "preconnect" in rel.lower()):
            links[(rel.lower(), href)] = tag
    p["links"] = links
    fonts, raw_of = Counter(), {}
    for m in FONT_RE.finditer(html):
        val, _ = split_val(m.group(1))
        n = norm_font(val)
        if skip_font(n):
            continue
        fonts[n] += 1
        raw_of.setdefault(n, val.replace('"', "'"))
    p["fonts"] = fonts
    p["primary"] = raw_of[fonts.most_common(1)[0][0]] if fonts else None
    p["colors"] = set(c.lower() for c in re.findall(r"#[0-9a-fA-F]{3,8}\b", html))
    p["h1"] = len(re.findall(r"<h1\b", html, re.I))
    blocks = {}
    for t in BLOCK_TAGS:
        m = get_block(html, t)
        if m:
            blocks[t] = m
    p["blocks"] = blocks
    hb, nb = blocks.get("header"), blocks.get("nav")
    p["nav_in_header"] = bool(hb and nb and nb.start() >= hb.start() and nb.end() <= hb.end())
    return p


# ---------- check ----------
def check_page(text, ref, strict):
    p = analyze(text)
    issues = []  # (message, fixable)
    if ref["lang"] and not p["lang"]:
        issues.append(("Missing lang attribute on <html>", True))
    elif ref["lang"] and p["lang"] != ref["lang"]:
        issues.append(("lang is '%s' but model uses '%s'" % (p["lang"], ref["lang"]), False))
    if ref["charset"] and not p["charset"]:
        issues.append(("Missing charset meta tag", True))
    if ref["viewport"] and not p["viewport"]:
        issues.append(("Missing viewport meta tag", True))
    if ref["title"] and not p["title"]:
        issues.append(("Missing or empty <title>", False))
    for key in ref["links"]:
        if key not in p["links"]:
            issues.append(("Missing <link> from model: %s" % key[1], True))
    for key in p["links"]:
        if key not in ref["links"]:
            issues.append(("Extra <link> not in model: %s" % key[1], False))
    for t in BLOCK_TAGS:
        rb, pb = ref["blocks"].get(t), p["blocks"].get(t)
        if t == "nav" and ref["nav_in_header"]:
            continue
        if rb and not pb:
            issues.append(("Missing <%s>" % t, t in ("header", "footer")))
        elif rb and pb and signature(rb.group(0), strict) != signature(pb.group(0), strict):
            issues.append(("<%s> differs from the model" % t, True))
        elif pb and not rb:
            issues.append(("<%s> exists but the model has none" % t, False))
    for f in p["fonts"]:
        if ref["fonts"] and f not in ref["fonts"]:
            issues.append(("Font not used in model: %s" % f, True))
    extra = sorted(p["colors"] - ref["colors"]) if ref["colors"] else []
    if extra:
        issues.append(("Colors not in model: %s%s" % (", ".join(extra[:6]), " ..." if len(extra) > 6 else ""), False))
    if p["h1"] != 1:
        issues.append(("%d <h1> tags (expected 1)" % p["h1"], False))
    return issues


# ---------- fix ----------
def fix_page(text, ref, strict, fix_fonts):
    changes = []
    p = analyze(text)

    if ref["lang"] and not p["lang"]:
        text, n = re.subn(r"<html\b", '<html lang="%s"' % ref["lang"], text, count=1, flags=re.I)
        if n:
            changes.append("added lang attribute")

    head_add = ""
    if ref["charset"] and not p["charset"]:
        head_add += "\n    " + ref["charset"]
        changes.append("added charset meta")
    if ref["viewport"] and not p["viewport"]:
        head_add += "\n    " + ref["viewport"]
        changes.append("added viewport meta")
    m = re.search(r"<head\b[^>]*>", text, re.I)
    if head_add and m:
        text = text[: m.end()] + head_add + text[m.end():]

    link_add = ""
    for key, tag in ref["links"].items():
        if key not in p["links"]:
            link_add += "\n    " + tag
            changes.append("added link: " + key[1])
    m = re.search(r"</head>", text, re.I)
    if link_add and m:
        text = text[: m.start()] + link_add.lstrip("\n") + "\n" + text[m.start():]

    for t in BLOCK_TAGS:
        rb = ref["blocks"].get(t)
        if not rb or (t == "nav" and ref["nav_in_header"]):
            continue
        rb_text = rb.group(0)
        pm = get_block(text, t)
        if pm:
            if signature(rb_text, strict) != signature(pm.group(0), strict):
                text = text[: pm.start()] + rb_text + text[pm.end():]
                changes.append("replaced <%s> with the model's" % t)
        elif t == "header":
            bm = re.search(r"<body\b[^>]*>", text, re.I)
            if bm:
                text = text[: bm.end()] + "\n" + rb_text + text[bm.end():]
                changes.append("inserted <header>")
        elif t == "footer":
            bm = re.search(r"</body>", text, re.I)
            if bm:
                text = text[: bm.start()] + rb_text + "\n" + text[bm.start():]
                changes.append("inserted <footer>")

    if fix_fonts and ref["fonts"] and ref["primary"]:
        count = [0]

        def repl(m):
            val, tail = split_val(m.group(1))
            n = norm_font(val)
            if skip_font(n) or n in ref["fonts"]:
                return m.group(0)
            count[0] += 1
            return m.group(0)[: m.start(1) - m.start(0)] + ref["primary"] + tail

        text = FONT_RE.sub(repl, text)
        if count[0]:
            changes.append("unified %d font-family value(s) to the model's main font" % count[0])
    return text, changes


# ---------- backup / restore ----------
def make_backup_dir(folder):
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    d = os.path.join(folder, BACKUP_DIR, stamp)
    os.makedirs(d, exist_ok=True)
    return d


def backup_file(folder, backup_dir, path):
    dest = os.path.join(backup_dir, os.path.relpath(path, folder))
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    shutil.copy2(path, dest)


def latest_backup(folder):
    root = os.path.join(folder, BACKUP_DIR)
    if not os.path.isdir(root):
        return None
    dirs = sorted(d for d in os.listdir(root) if os.path.isdir(os.path.join(root, d)))
    return os.path.join(root, dirs[-1]) if dirs else None


def restore_backup(folder, backup_dir):
    restored = 0
    for root, _, files in os.walk(backup_dir):
        for name in files:
            src = os.path.join(root, name)
            dest = os.path.join(folder, os.path.relpath(src, backup_dir))
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            shutil.copy2(src, dest)
            restored += 1
    return restored


# ---------- GUI ----------
class App(tk.Tk if tk else object):
    def __init__(self):
        super().__init__()
        self.title("HTML Consistency Checker")
        self.geometry("920x680")
        self.folder = tk.StringVar()
        self.model = tk.StringVar()
        self.recursive = tk.BooleanVar(value=True)
        self.strict = tk.BooleanVar(value=False)
        self.fix_fonts = tk.BooleanVar(value=True)

        top = tk.Frame(self)
        top.pack(fill="x", padx=10, pady=8)
        top.columnconfigure(1, weight=1)
        tk.Label(top, text="Folder:").grid(row=0, column=0, sticky="w")
        tk.Entry(top, textvariable=self.folder).grid(row=0, column=1, sticky="ew", padx=6, pady=2)
        tk.Button(top, text="Browse...", command=self.pick_folder).grid(row=0, column=2)
        tk.Label(top, text="Model file:").grid(row=1, column=0, sticky="w")
        tk.Entry(top, textvariable=self.model).grid(row=1, column=1, sticky="ew", padx=6, pady=2)
        tk.Button(top, text="Browse...", command=self.pick_model).grid(row=1, column=2)

        opts = tk.Frame(self)
        opts.pack(fill="x", padx=10)
        tk.Checkbutton(opts, text="Include subfolders", variable=self.recursive).pack(side="left")
        tk.Checkbutton(opts, text="Strict compare (exact header/nav/footer markup)",
                       variable=self.strict).pack(side="left", padx=12)
        tk.Checkbutton(opts, text="Fix fonts too", variable=self.fix_fonts).pack(side="left")

        btns = tk.Frame(self)
        btns.pack(fill="x", padx=10, pady=8)
        tk.Button(btns, text="Check (no changes)", command=self.do_check).pack(side="left")
        tk.Button(btns, text="Fix (with backup)", command=self.do_fix).pack(side="left", padx=8)
        tk.Button(btns, text="Restore last backup", command=self.do_restore).pack(side="left")

        self.out = scrolledtext.ScrolledText(self, font=("Consolas", 10), wrap="word")
        self.out.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self.out.tag_config("bad", foreground="#b00020")
        self.out.tag_config("ok", foreground="#1b7f3b")
        self.out.tag_config("head", font=("Consolas", 10, "bold"))

    def log(self, text, tag=None):
        self.out.insert("end", text + "\n", tag)
        self.out.see("end")
        self.update_idletasks()

    def pick_folder(self):
        d = filedialog.askdirectory()
        if d:
            self.folder.set(d)

    def pick_model(self):
        f = filedialog.askopenfilename(filetypes=[("HTML files", "*.html *.htm")])
        if f:
            self.model.set(f)
            if not self.folder.get():
                self.folder.set(os.path.dirname(f))

    def setup(self):
        folder, model = self.folder.get().strip(), self.model.get().strip()
        if not os.path.isdir(folder):
            messagebox.showerror("Folder", "Choose a valid folder.")
            return None
        if not os.path.isfile(model):
            messagebox.showerror("Model file", "Choose a valid model HTML file.")
            return None
        try:
            ref = analyze(read(model))
        except UnicodeDecodeError:
            messagebox.showerror("Model file", "The model file is not UTF-8 encoded.")
            return None
        pages = [p for p in find_html(folder, self.recursive.get())
                 if os.path.abspath(p) != os.path.abspath(model)]
        self.out.delete("1.0", "end")
        self.log("Model: " + os.path.basename(model), "head")
        self.log("  fonts: " + (", ".join(ref["fonts"]) or "none found"))
        self.log("  stylesheets/links: %d   header/nav/footer: %s" % (
            len(ref["links"]), ", ".join(ref["blocks"]) or "none"))
        self.log("Scanning %d page(s)...\n" % len(pages))
        return folder, ref, pages

    def do_check(self):
        s = self.setup()
        if not s:
            return
        folder, ref, pages = s
        clean = total = fixable = 0
        for path in pages:
            rel = os.path.relpath(path, folder)
            try:
                issues = check_page(read(path), ref, self.strict.get())
            except UnicodeDecodeError:
                self.log("%s: skipped (not UTF-8)" % rel, "bad")
                continue
            if not issues:
                clean += 1
                self.log("OK   " + rel, "ok")
                continue
            self.log("     " + rel, "head")
            for msg, fx in issues:
                total += 1
                fixable += fx
                self.log("     - %s%s" % (msg, "  [fixable]" if fx else ""), "bad")
        self.log("\nDone: %d clean, %d page(s) with issues (%d issues, %d fixable)." % (
            clean, len(pages) - clean, total, fixable), "head")

    def do_fix(self):
        s = self.setup()
        if not s:
            return
        folder, ref, pages = s
        plan = []
        for path in pages:
            try:
                text = read(path)
            except UnicodeDecodeError:
                self.log("%s: skipped (not UTF-8)" % os.path.relpath(path, folder), "bad")
                continue
            new, changes = fix_page(text, ref, self.strict.get(), self.fix_fonts.get())
            if new != text:
                plan.append((path, new, changes))
        if not plan:
            self.log("Nothing to fix.", "ok")
            return
        if not messagebox.askyesno(
                "Confirm",
                "%d file(s) will be modified.\nOriginals are backed up first in:\n%s\n\nContinue?"
                % (len(plan), os.path.join(folder, BACKUP_DIR))):
            self.log("Cancelled. No files changed.")
            return
        bdir = make_backup_dir(folder)
        for path, new, changes in plan:
            backup_file(folder, bdir, path)
            write(path, new)
            self.log("FIXED " + os.path.relpath(path, folder), "ok")
            for c in changes:
                self.log("     - " + c)
        self.log("\n%d file(s) fixed. Backup: %s" % (len(plan), bdir), "head")
        self.log("Run Check again to see what's left (some issues can't be auto-fixed).")

    def do_restore(self):
        folder = self.folder.get().strip()
        b = latest_backup(folder) if os.path.isdir(folder) else None
        if not b:
            messagebox.showinfo("Restore", "No backups found in this folder.")
            return
        if messagebox.askyesno("Restore", "Restore files from:\n%s\n\nThis overwrites the current versions." % b):
            n = restore_backup(folder, b)
            self.log("Restored %d file(s) from %s" % (n, b), "ok")


if __name__ == "__main__":
    App().mainloop()
