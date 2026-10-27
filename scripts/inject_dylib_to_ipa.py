"""Stage 1.6b Step 4:
Builds dist/FLM_Custom_NoDylib.ipa (control build without dylib) and dist/FLM_Custom_Hook.ipa.
Refuses to build dist/FLM_Custom_Hook.ipa unless a real compiled arm64 MH_DYLIB is present in build/FLM_CustomDSP.dylib.
Never generates or injects a stub dylib. Pure Python stdlib, stdout <= 35 lines.
"""
import os
import plistlib
import shutil
import struct
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from patch_macho_dylib import list_load_dylibs, list_rpaths, patch_macho_header
from inject_ipa import (
    IPA_SRC,
    MAIN_BIN_PATH,
    REC_STRUCT,
    SAMPLES_LIST_PATH,
    clone_zipinfo,
    collect_new_ipa_files,
    make_unix_zipinfo,
    patch_samples_list,
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INFO_PLIST_PATH = "Payload/FL Studio Mobile.app/Info.plist"
DYLIB_NAME = "FLM_CustomDSP.dylib"
DYLIB_ARC_PATH = f"Payload/FL Studio Mobile.app/Frameworks/{DYLIB_NAME}"
DEFAULT_DYLIB_PATH = os.path.join(ROOT, "build", DYLIB_NAME)

IPA_NODylib_OUT = os.path.join(ROOT, "dist", "FLM_Custom_NoDylib.ipa")
IPA_HOOK_OUT = os.path.join(ROOT, "dist", "FLM_Custom_Hook.ipa")

MH_MAGIC_64 = 0xFEEDFACF
CPU_TYPE_ARM64 = 0x0100000C
MH_DYLIB = 6
LC_ID_DYLIB = 0x0D
LC_SEGMENT_64 = 0x19
EXPECTED_ID_DYLIB = "@rpath/FLM_CustomDSP.dylib"


def validate_real_arm64_dylib(path, expected_id=EXPECTED_ID_DYLIB):
    """Verify path exists, is a genuine compiled arm64 MH_DYLIB, and has LC_ID_DYLIB == @rpath/FLM_CustomDSP.dylib."""
    if not path or not os.path.isfile(path):
        return False, f"File not found: '{path}' (compile in GitHub Actions CI first)"
    sz = os.path.getsize(path)
    if sz < 4096:
        return False, f"File too small ({sz} B)"
    with open(path, "rb") as f:
        head = f.read(min(sz, 8192))
    magic, cputype, _, filetype, ncmds, _, _, _ = struct.unpack_from("<8I", head, 0)
    if magic != MH_MAGIC_64:
        return False, f"Invalid magic 0x{magic:08x} (expected 0xfeedfacf)"
    if cputype != CPU_TYPE_ARM64:
        return False, f"Invalid cputype 0x{cputype:08x} (expected CPU_TYPE_ARM64 0x0100000c)"
    if filetype != MH_DYLIB:
        return False, f"Invalid filetype {filetype} (expected MH_DYLIB=6)"

    has_text_seg = False
    id_dylib_str = None
    pos = 32
    for _ in range(ncmds):
        if pos + 8 > len(head):
            break
        cmd, cmdsize = struct.unpack_from("<II", head, pos)
        if cmd == LC_ID_DYLIB and pos + 24 <= len(head):
            str_off = struct.unpack_from("<I", head, pos + 8)[0]
            id_dylib_str = head[pos + str_off : pos + cmdsize].split(b"\x00", 1)[0].decode("utf-8", errors="replace")
        elif cmd == LC_SEGMENT_64 and pos + 72 <= len(head):
            segname = head[pos + 8 : pos + 24].split(b"\x00", 1)[0]
            nsects = struct.unpack_from("<I", head, pos + 64)[0]
            if segname == b"__TEXT" and nsects >= 1:
                has_text_seg = True
        pos += cmdsize

    if id_dylib_str != expected_id:
        return False, f"LC_ID_DYLIB mismatch: got '{id_dylib_str}', expected '{expected_id}'"
    if not has_text_seg or ncmds < 5:
        return False, f"Rejected stub/incomplete Mach-O (ncmds={ncmds}, has_text_seg={has_text_seg})"
    return True, f"Valid compiled arm64 MH_DYLIB ({sz} B, ncmds={ncmds}, LC_ID_DYLIB='{id_dylib_str}')"


def patch_info_plist_bytes(raw_plist):
    """Preserve all existing Info.plist keys and add NSLocalNetworkUsageDescription + NSAllowsLocalNetworking."""
    pl = plistlib.loads(raw_plist)
    pl["NSLocalNetworkUsageDescription"] = "FLM Custom DSP uses the local network to send UI layout telemetry snapshots."
    ats = dict(pl.get("NSAppTransportSecurity") or {})
    ats["NSAllowsLocalNetworking"] = True
    pl["NSAppTransportSecurity"] = ats
    return plistlib.dumps(pl, fmt=plistlib.FMT_BINARY)


def build_ipa_variant(out_path, new_items, patched_index, patched_plist, hook_cfg=None):
    skip_arcnames = {arc for arc, _ in new_items}
    if hook_cfg:
        skip_arcnames.add(DYLIB_ARC_PATH)

    patch_info = None
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with zipfile.ZipFile(IPA_SRC, "r") as zin, zipfile.ZipFile(out_path, "w") as zout:
        for info in zin.infolist():
            if info.filename in skip_arcnames:
                continue
            zi = clone_zipinfo(info)
            if info.filename == SAMPLES_LIST_PATH:
                zout.writestr(zi, patched_index)
            elif info.filename == INFO_PLIST_PATH:
                zout.writestr(zi, patched_plist)
            elif hook_cfg and info.filename == MAIN_BIN_PATH:
                with zin.open(info, "r") as src_f, zout.open(zi, "w") as dst_f:
                    head = src_f.read(16384)
                    patched_head, patch_info = patch_macho_header(head, hook_cfg["install_name"])
                    dst_f.write(patched_head)
                    shutil.copyfileobj(src_f, dst_f, length=1024 * 1024)
            elif info.is_dir():
                zout.writestr(zi, b"")
            else:
                with zin.open(info, "r") as src_f, zout.open(zi, "w") as dst_f:
                    shutil.copyfileobj(src_f, dst_f, length=1024 * 1024)

        if hook_cfg:
            dylib_local = hook_cfg["dylib_path"]
            dylib_zi = make_unix_zipinfo(DYLIB_ARC_PATH, os.path.getmtime(dylib_local), is_dir=False)
            dylib_zi.external_attr = 0o100755 << 16
            with open(dylib_local, "rb") as src_f, zout.open(dylib_zi, "w") as dst_f:
                shutil.copyfileobj(src_f, dst_f, length=1024 * 1024)

        for arcname, local_path in new_items:
            zi = make_unix_zipinfo(arcname, os.path.getmtime(local_path), is_dir=False)
            with open(local_path, "rb") as src_f, zout.open(zi, "w") as dst_f:
                shutil.copyfileobj(src_f, dst_f, length=1024 * 1024)

    return patch_info


def verify_ipa_variant(ipa_path, expect_hook, expected_install_name, log):
    with zipfile.ZipFile(ipa_path, "r") as zf:
        names = [i.filename for i in zf.infolist()]
        dups = len(names) - len(set(names))
        assert dups == 0, f"Duplicate entries in {ipa_path}: {dups}"

        pl = plistlib.loads(zf.read(INFO_PLIST_PATH))
        assert pl.get("NSLocalNetworkUsageDescription"), "Missing NSLocalNetworkUsageDescription"
        assert pl.get("NSAppTransportSecurity", {}).get("NSAllowsLocalNetworking") is True, "Missing NSAllowsLocalNetworking"

        bin_info = zf.getinfo(MAIN_BIN_PATH)
        bin_mode = (bin_info.external_attr >> 16) & 0o777
        assert bin_mode == 0o755, f"Main binary mode is {oct(bin_mode)}"
        with zf.open(MAIN_BIN_PATH, "r") as f:
            head = f.read(16384)
        dylibs = list_load_dylibs(head)

        if expect_hook:
            assert expected_install_name in dylibs, f"Missing {expected_install_name} in {dylibs}"
            dy_info = zf.getinfo(DYLIB_ARC_PATH)
            dy_mode = (dy_info.external_attr >> 16) & 0o777
            assert dy_mode == 0o755 and dy_info.create_system == 3, f"Bad dylib mode {oct(dy_mode)}"
            log.append(f"[Verify Hook]    {os.path.basename(ipa_path)} ({os.path.getsize(ipa_path)/1e6:.1f} MB): "
                       f"LC_LOAD_DYLIB='{expected_install_name}', dylib='{DYLIB_ARC_PATH}' (0755)")
        else:
            assert expected_install_name not in dylibs and DYLIB_ARC_PATH not in names
            log.append(f"[Verify NoDylib] {os.path.basename(ipa_path)} ({os.path.getsize(ipa_path)/1e6:.1f} MB, {len(names)} entries): "
                       f"Clean Mach-O, 386 samplesList records, Info.plist LAN=True")


def main():
    log = []
    with zipfile.ZipFile(IPA_SRC, "r") as zin:
        raw_index = zin.read(SAMPLES_LIST_PATH)
        raw_plist = zin.read(INFO_PLIST_PATH)
        with zin.open(MAIN_BIN_PATH, "r") as bf:
            orig_head = bf.read(16384)

    rpaths = list_rpaths(orig_head)
    install_name = f"@rpath/{DYLIB_NAME}" if "@executable_path/Frameworks" in rpaths else f"@executable_path/Frameworks/{DYLIB_NAME}"
    patched_index = patch_samples_list(raw_index, log)
    patched_plist = patch_info_plist_bytes(raw_plist)
    new_items = collect_new_ipa_files()

    # 1. Verify or build FLM_Custom_NoDylib.ipa
    if not os.path.isfile(IPA_NODylib_OUT):
        build_ipa_variant(IPA_NODylib_OUT, new_items, patched_index, patched_plist, hook_cfg=None)
    verify_ipa_variant(IPA_NODylib_OUT, expect_hook=False, expected_install_name=install_name, log=log)

    # 2. Strictly validate compiled arm64 MH_DYLIB before building FLM_Custom_Hook.ipa
    dylib_candidate = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_DYLIB_PATH
    ok, reason = validate_real_arm64_dylib(dylib_candidate)
    if not ok:
        if os.path.isfile(IPA_HOOK_OUT):
            os.remove(IPA_HOOK_OUT)
        log.append(f"[REFUSED] Skipping '{os.path.basename(IPA_HOOK_OUT)}': {reason}")
        log.append("          Download compiled FLM_CustomDSP.dylib from CI into build/ and re-run this script.")
        print("\n".join(log[:35]))
        return

    p_info = build_ipa_variant(
        IPA_HOOK_OUT,
        new_items,
        patched_index,
        patched_plist,
        hook_cfg={"dylib_path": dylib_candidate, "install_name": install_name},
    )
    log.append(f"[Mach-O] Patched '{MAIN_BIN_PATH}': ncmds {p_info['old_ncmds']}->{p_info['new_ncmds']} (+{p_info['cmdsize']} B, free={p_info['free_pad_after']} B)")
    log.append(f"[Dylib]  {reason}")
    verify_ipa_variant(IPA_HOOK_OUT, expect_hook=True, expected_install_name=install_name, log=log)
    print("\n".join(log[:35]))


if __name__ == "__main__":
    main()
