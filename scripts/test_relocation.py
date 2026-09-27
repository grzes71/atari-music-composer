"""Test player relocatability across multiple installation addresses."""

import subprocess
from pathlib import Path

def test_relocation():
    addresses = ["$6000", "$7000", "$8000", "$A000"]
    mads_exe = Path("tools/mads/mads.exe")
    assert mads_exe.exists(), "tools/mads/mads.exe not found"

    for addr in addresses:
        src = f"""
    org {addr}
    ldx #<song_data
    ldy #>song_data
    jsr music_init
    jsr music_play
    jsr music_update
    jsr music_stop
    rts

    icl '../player.asm'
    icl 'test_export.asm'
"""
        tag = addr.replace("$", "")
        asm_p = Path(f"experiments/test_{tag}.asm")
        asm_p.write_text(src, encoding="utf-8")
        xex_p = Path(f"experiments/test_{tag}.xex")

        res = subprocess.run([str(mads_exe), str(asm_p), f"-o:{xex_p}"], capture_output=True, text=True)
        assert res.returncode == 0, f"MADS failed at {addr}: {res.stderr or res.stdout}"
        size = xex_p.stat().st_size
        print(f"[PASS] Relocation at {addr}: compiled cleanly -> {size} bytes ({xex_p})")

    # Test split relocation: player at $5000, music data at $8500
    src_split = """
    org $5000
    ldx #<song_data
    ldy #>song_data
    jsr music_init
    jsr music_play
    jsr music_update
    jsr music_stop
    rts

    icl '../player.asm'

    org $8500
    icl 'test_export.asm'
"""
    split_asm = Path("experiments/test_split.asm")
    split_asm.write_text(src_split, encoding="utf-8")
    split_xex = Path("experiments/test_split.xex")
    res = subprocess.run([str(mads_exe), str(split_asm), f"-o:{split_xex}"], capture_output=True, text=True)
    assert res.returncode == 0, f"Split test failed: {res.stderr or res.stdout}"
    print(f"[PASS] Independent placement: Player at $5000, Data at $8500 -> compiled cleanly ({split_xex})")

if __name__ == "__main__":
    test_relocation()
