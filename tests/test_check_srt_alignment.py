import importlib.util
import json
import sys
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "check_srt_alignment.py"
SPEC = importlib.util.spec_from_file_location("check_srt_alignment", MODULE_PATH)
check_srt_alignment = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules["check_srt_alignment"] = check_srt_alignment
SPEC.loader.exec_module(check_srt_alignment)


def write_srt(path: Path, blocks: list[tuple[int, str, str]]) -> None:
    parts = []
    for index, timing, text in blocks:
        parts.append(f"{index}\n{timing}\n{text}\n")
    path.write_text("\n".join(parts), encoding="utf-8")


def test_aligned_srt_returns_zero(tmp_path, capsys):
    left = tmp_path / "zh-cn.srt"
    right = tmp_path / "en.srt"
    blocks = [
        (1, "00:00:01,000 --> 00:00:02,000", "你好"),
        (2, "00:00:03,000 --> 00:00:04,500", "世界"),
    ]
    write_srt(left, blocks)
    write_srt(right, blocks)

    code = check_srt_alignment.main([str(left), str(right)])

    assert code == 0
    assert "status: aligned" in capsys.readouterr().out


def test_time_mismatch_returns_one(tmp_path, capsys):
    left = tmp_path / "zh-cn.srt"
    right = tmp_path / "en.srt"
    write_srt(left, [(1, "00:00:01,000 --> 00:00:02,000", "你好")])
    write_srt(right, [(1, "00:00:01,200 --> 00:00:02,000", "hello")])

    code = check_srt_alignment.main([str(left), str(right)])

    assert code == 1
    output = capsys.readouterr().out
    assert "status: not aligned" in output
    assert "start-time" in output
    assert "delta=200ms" in output


def test_tolerance_allows_small_time_drift(tmp_path):
    left = tmp_path / "zh-cn.srt"
    right = tmp_path / "en.srt"
    write_srt(left, [(1, "00:00:01,000 --> 00:00:02,000", "你好")])
    write_srt(right, [(1, "00:00:01,020 --> 00:00:02,040", "hello")])

    code = check_srt_alignment.main(
        [str(left), str(right), "--tolerance-ms", "50"]
    )

    assert code == 0


def test_json_output_is_single_document(tmp_path, capsys):
    left = tmp_path / "zh-cn.srt"
    right = tmp_path / "en.srt"
    write_srt(left, [(1, "00:00:01,000 --> 00:00:02,000", "你好")])
    write_srt(right, [(2, "00:00:01,000 --> 00:00:02,000", "hello")])

    code = check_srt_alignment.main([str(left), str(right), "--json"])

    assert code == 1
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["aligned"] is False
    assert payload["mismatches"][0]["reason"] == "index"
    assert captured.err == ""


def test_malformed_srt_returns_two(tmp_path, capsys):
    left = tmp_path / "zh-cn.srt"
    right = tmp_path / "en.srt"
    left.write_text("not-an-index\n00:00:01,000 --> 00:00:02,000\n你好\n")
    write_srt(right, [(1, "00:00:01,000 --> 00:00:02,000", "hello")])

    code = check_srt_alignment.main([str(left), str(right)])

    assert code == 2
    assert "error:" in capsys.readouterr().err
