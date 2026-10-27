"""Phase 3: Direct import bundle, samplesList.data index patching, and streaming IPA injection.
Strictly stdlib only, stdout <= 40 lines.
"""
import os
import shutil
import struct
import time
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IPA_SRC = os.path.join(ROOT, "target.ipa")
DIST_INSTR = os.path.join(ROOT, "dist", "instruments")
DIRECT_DIR = os.path.join(ROOT, "dist", "direct_import")
MY_INSTR_DIR = os.path.join(DIRECT_DIR, "My Instruments")
IPA_OUT = os.path.join(ROOT, "dist", "FLM_Custom.ipa")

SAMPLES_LIST_PATH = "Payload/FL Studio Mobile.app/samplesList.data"
MAIN_BIN_PATH = "Payload/FL Studio Mobile.app/FL Studio Mobile"
EXEC_PATHS = {
    MAIN_BIN_PATH,
    "Payload/FL Studio Mobile.app/Frameworks/lame.framework/lame",
    "Payload/FL Studio Mobile.app/Frameworks/SatellaJailed.dylib",
    "Payload/FL Studio Mobile.app/Frameworks/Audiobus.framework/Audiobus",
}
DW_BASE = "Payload/FL Studio Mobile.app/DirectWave Samples"

REC_STRUCT = struct.Struct("<H128sH")

# Mapping: (custom_instrument_name, category_folder, donor_name)
CUSTOM_BANKS = [
    ("Custom_Dark_Pluck", "Guitar", "Purity Guitar"),
    ("Custom_Sub_808", "Synth Bass", "Ogun Clockwork"),
    ("Custom_LoFi_Keys", "Keyboard", "Morphine Clavinet"),
]


def build_direct_import(log):
    if os.path.exists(DIRECT_DIR):
        shutil.rmtree(DIRECT_DIR)
    os.makedirs(MY_INSTR_DIR, exist_ok=True)

    copied_dwp = 0
    copied_wav = 0
    for name, cat, _ in CUSTOM_BANKS:
        src_cat = os.path.join(DIST_INSTR, cat)
        src_dwp = os.path.join(src_cat, name + ".dwp")
        src_dir = os.path.join(src_cat, name)

        # 1a. Copy flat into dist/direct_import/My Instruments/
        shutil.copy2(src_dwp, os.path.join(MY_INSTR_DIR, name + ".dwp"))
        copied_dwp += 1
        dst_sample_dir = os.path.join(MY_INSTR_DIR, name)
        shutil.copytree(src_dir, dst_sample_dir)
        wavs = [f for f in os.listdir(dst_sample_dir) if f.lower().endswith(".wav")]
        copied_wav += len(wavs)

        # 1b. Create per-instrument .zip archive in dist/direct_import/
        zip_path = os.path.join(DIRECT_DIR, name + ".zip")
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.write(src_dwp, name + ".dwp")
            for fn in sorted(os.listdir(src_dir)):
                full = os.path.join(src_dir, fn)
                if os.path.isfile(full):
                    zf.write(full, f"{name}/{fn}")

    log.append(f"[1/3] Direct import ready: {MY_INSTR_DIR}")
    log.append(f"      Copied {copied_dwp} .dwp banks + {copied_wav} sample files (+ {copied_dwp} .zip packs)")


def patch_samples_list(raw_bytes, log):
    if len(raw_bytes) % REC_STRUCT.size != 0:
        raise ValueError(f"Unexpected samplesList.data size: {len(raw_bytes)}")
    num_records = len(raw_bytes) // REC_STRUCT.size
    donor_cats = {}
    for i in range(num_records):
        rec_id, name_raw, cat_id = REC_STRUCT.unpack_from(raw_bytes, i * REC_STRUCT.size)
        name = name_raw.split(b"\x00", 1)[0].decode("latin1")
        donor_cats[name] = cat_id

    patched = bytearray(raw_bytes)
    added_summary = []
    for offset, (custom_name, _, donor_name) in enumerate(CUSTOM_BANKS, start=1):
        if donor_name not in donor_cats:
            raise KeyError(f"Donor '{donor_name}' not found in samplesList.data")
        cat_id = donor_cats[donor_name]
        next_id = num_records + offset  # 384, 385, 386
        name_bytes = custom_name.encode("ascii")[:127].ljust(128, b"\x00")
        patched += REC_STRUCT.pack(next_id, name_bytes, cat_id)
        added_summary.append(f"#{next_id} {custom_name} (cat={cat_id} from '{donor_name}')")

    log.append(f"[2/3] Patched samplesList.data: {num_records} -> { len(patched) // REC_STRUCT.size } records ({len(raw_bytes)} -> {len(patched)} B)")
    for item in added_summary:
        log.append(f"      + {item}")
    return bytes(patched)


def clone_zipinfo(src_info):
    zi = zipfile.ZipInfo(filename=src_info.filename, date_time=src_info.date_time)
    zi.compress_type = src_info.compress_type
    zi.comment = src_info.comment
    zi.extra = src_info.extra
    zi.create_system = src_info.create_system
    zi.create_version = src_info.create_version
    zi.extract_version = src_info.extract_version
    zi.internal_attr = src_info.internal_attr
    zi.external_attr = src_info.external_attr
    if src_info.filename in EXEC_PATHS:
        zi.external_attr = (0o100755 << 16) | (src_info.external_attr & 0xFFFF)
    zi.flag_bits = src_info.flag_bits & ~0x08  # clear data-descriptor bit when writing known size
    return zi


def make_unix_zipinfo(arcname, mtime=None, is_dir=False):
    t = time.localtime(mtime or time.time())[:6]
    if is_dir and not arcname.endswith("/"):
        arcname += "/"
    zi = zipfile.ZipInfo(filename=arcname, date_time=t)
    zi.create_system = 3  # UNIX
    zi.create_version = 20
    zi.extract_version = 20
    if is_dir:
        zi.compress_type = zipfile.ZIP_STORED
        zi.external_attr = (0o040755 << 16) | 0x10
    else:
        zi.compress_type = zipfile.ZIP_DEFLATED
        zi.external_attr = 0o100644 << 16
    return zi


def collect_new_ipa_files():
    """Return list of (arcname, local_path) for all generated files in dist/instruments/."""
    items = []
    for name, cat, _ in CUSTOM_BANKS:
        src_cat = os.path.join(DIST_INSTR, cat)
        dwp_local = os.path.join(src_cat, name + ".dwp")
        dwp_arc = f"{DW_BASE}/{cat}/{name}.dwp"
        items.append((dwp_arc, dwp_local))

        sample_dir = os.path.join(src_cat, name)
        for fn in sorted(os.listdir(sample_dir)):
            full = os.path.join(sample_dir, fn)
            if os.path.isfile(full):
                items.append((f"{DW_BASE}/{cat}/{name}/{fn}", full))
    return items


def build_custom_ipa(log):
    new_items = collect_new_ipa_files()
    new_arcnames = {arc for arc, _ in new_items}

    with zipfile.ZipFile(IPA_SRC, "r") as zin:
        raw_index = zin.read(SAMPLES_LIST_PATH)
        patched_index = patch_samples_list(raw_index, log)

        os.makedirs(os.path.dirname(IPA_OUT), exist_ok=True)
        copied_count = 0
        with zipfile.ZipFile(IPA_OUT, "w") as zout:
            for info in zin.infolist():
                if info.filename in new_arcnames:
                    continue
                zi = clone_zipinfo(info)
                if info.filename == SAMPLES_LIST_PATH:
                    zout.writestr(zi, patched_index)
                elif info.is_dir():
                    zout.writestr(zi, b"")
                else:
                    # Stream copy without unpacking to disk
                    with zin.open(info, "r") as src_f, zout.open(zi, "w") as dst_f:
                        shutil.copyfileobj(src_f, dst_f, length=1024 * 1024)
                copied_count += 1

            # Inject new instruments and samples
            for arcname, local_path in new_items:
                zi = make_unix_zipinfo(arcname, os.path.getmtime(local_path), is_dir=False)
                with open(local_path, "rb") as src_f, zout.open(zi, "w") as dst_f:
                    shutil.copyfileobj(src_f, dst_f, length=1024 * 1024)

    log.append(f"[3/3] Built {IPA_OUT} ({os.path.getsize(IPA_OUT) / 1e6:.1f} MB)")
    log.append(f"      Copied {copied_count} original entries + injected {len(new_items)} new entries")


def verify_custom_ipa(log):
    with zipfile.ZipFile(IPA_OUT, "r") as zf:
        infos = zf.infolist()
        names = [i.filename for i in infos]
        dups = len(names) - len(set(names))

        # Check main binary permissions
        bin_info = zf.getinfo(MAIN_BIN_PATH)
        bin_mode = (bin_info.external_attr >> 16) & 0o777
        bin_sys = bin_info.create_system

        # Check patched samplesList.data
        idx_bytes = zf.read(SAMPLES_LIST_PATH)
        idx_count = len(idx_bytes) // REC_STRUCT.size

        # Check injected files UNIX mode
        injected_Info = [zf.getinfo(arc) for arc, _ in collect_new_ipa_files()]
        inj_modes = {(i.create_system, (i.external_attr >> 16) & 0o777777) for i in injected_Info}

        assert dups == 0, f"Duplicate ZIP entries found: {dups}"
        assert idx_count == 386 and len(idx_bytes) == 50952, f"Bad index size: {len(idx_bytes)}"
        assert bin_mode == 0o755, f"Main binary mode is {oct(bin_mode)}, expected 0o755"
        assert inj_modes == {(3, 0o100644)}, f"Unexpected injected attrs: {inj_modes}"

        log.append("Verification PASSED:")
        log.append(f"  - Total entries: {len(names)}, duplicates: {dups}")
        log.append(f"  - Main executable '{MAIN_BIN_PATH}': create_system={bin_sys}, mode={oct(bin_mode)}")
        log.append(f"  - Index '{SAMPLES_LIST_PATH}': {len(idx_bytes)} B ({idx_count} records)")
        log.append(f"  - Injected {len(injected_Info)} files: create_system=3, mode=0o100644")


def main():
    log = []
    build_direct_import(log)
    build_custom_ipa(log)
    verify_custom_ipa(log)
    print("\n".join(log[:40]))


if __name__ == "__main__":
    main()
