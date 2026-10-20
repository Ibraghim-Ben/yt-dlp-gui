from __future__ import annotations
import os
import pathlib
import struct
import xml.etree.ElementTree as ET


def elf_hash(source: str, comment: str = "") -> int:
    h = 0
    for s in (source, comment):
        for b in s.encode("utf-8"):
            h = ((h << 4) + b) & 0xFFFFFFFF
            g = h & 0xF0000000
            if g:
                h ^= g >> 24
            h &= ~g
    return h


def parse_ts(ts_path: pathlib.Path | str) -> list[dict]:
    tree = ET.parse(str(ts_path))
    root = tree.getroot()
    items = []
    for ctx in root.findall("context"):
        name_elem = ctx.find("name")
        ctx_name = name_elem.text if name_elem is not None and name_elem.text else ""
        for msg in ctx.findall("message"):
            src_elem = msg.find("source")
            tr_elem = msg.find("translation")
            comment_elem = msg.find("comment")
            src = src_elem.text if src_elem is not None and src_elem.text else ""
            tr = tr_elem.text if tr_elem is not None and tr_elem.text else ""
            comment = comment_elem.text if comment_elem is not None and comment_elem.text else ""
            if src and tr:
                items.append({
                    "context": ctx_name,
                    "source": src,
                    "translation": tr,
                    "comment": comment,
                })
    return items


def compile_qm(items: list[dict], qm_path: pathlib.Path | str, lang: str = "ru_RU") -> None:
    magic = bytes([
        0x3c, 0xb8, 0x64, 0x18, 0xca, 0xef, 0x9c, 0x95,
        0xcd, 0x21, 0x1c, 0xbf, 0x60, 0xa1, 0xbd, 0xdd
    ])
    entries = []
    msgs_buf = bytearray()
    for item in items:
        ctx = item["context"].encode("utf-8")
        src = item["source"].encode("utf-8")
        tr = item["translation"].encode("utf-16be")
        comment = item.get("comment", "").encode("utf-8")
        offset = len(msgs_buf)
        h = elf_hash(item["source"], item.get("comment", ""))
        entries.append((h, offset))
        msgs_buf.append(3)
        msgs_buf.extend(struct.pack(">I", len(tr)))
        msgs_buf.extend(tr)
        if comment:
            msgs_buf.append(8)
            msgs_buf.extend(struct.pack(">I", len(comment)))
            msgs_buf.extend(comment)
        msgs_buf.append(6)
        msgs_buf.extend(struct.pack(">I", len(src)))
        msgs_buf.extend(src)
        msgs_buf.append(7)
        msgs_buf.extend(struct.pack(">I", len(ctx)))
        msgs_buf.extend(ctx)
        msgs_buf.append(1)

    entries.sort(key=lambda x: x[0])
    hashes_buf = bytearray()
    for h, off in entries:
        hashes_buf.extend(struct.pack(">II", h, off))

    out = bytearray(magic)
    lang_bytes = lang.encode("utf-8")
    out.append(0xa7)
    out.extend(struct.pack(">I", len(lang_bytes)))
    out.extend(lang_bytes)
    out.append(0x42)
    out.extend(struct.pack(">I", len(hashes_buf)))
    out.extend(hashes_buf)
    out.append(0x69)
    out.extend(struct.pack(">I", len(msgs_buf)))
    out.extend(msgs_buf)

    target = pathlib.Path(qm_path)
    tmp_path = target.with_suffix(".qm.tmp")
    try:
        with open(tmp_path, "wb") as f:
            f.write(out)
        tmp_path.replace(target)
    except Exception:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass


def ensure_qm_compiled(ts_path: pathlib.Path | str, qm_path: pathlib.Path | str) -> None:
    p_ts = pathlib.Path(ts_path)
    p_qm = pathlib.Path(qm_path)
    if not p_ts.exists():
        return
    try:
        if not p_qm.exists() or p_ts.stat().st_mtime > p_qm.stat().st_mtime:
            items = parse_ts(p_ts)
            compile_qm(items, p_qm)
    except Exception:
        pass
